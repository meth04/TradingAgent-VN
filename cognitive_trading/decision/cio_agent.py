"""CIO intent generation for cognitive_trading using cards, debate, and episodic memory."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.decision.debate_engine import DebateResult
from cognitive_trading.decision.debate_trigger import action_direction
from cognitive_trading.governance.schemas import AnalysisCard, IntentTicket
from cognitive_trading.memory import CognitiveDB, EpisodicStore, PromotionEngine, StrategyStore
from vnstock.agents.prompting import Action
from vnstock.core.llm import LLMError, call_llm

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"(\{[\s\S]*\})")


@dataclass(slots=True)
class CIOAgent:
    """Generate the final IntentTicket from analyst evidence, playbooks, and debate output."""

    config: CognitiveConfig = CognitiveConfig()
    memory_db_path: Path | str | None = None
    memory_limit: int = 5
    temperature: float = 0.1
    cognitive_db: CognitiveDB | None = None
    episodic_store: EpisodicStore = field(init=False, repr=False)
    strategy_store: StrategyStore = field(init=False, repr=False)
    promotion_engine: PromotionEngine = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.episodic_store = EpisodicStore(
            db_path=self.memory_db_path,
            config=self.config,
            cognitive_db=self.cognitive_db,
        )
        self.strategy_store = StrategyStore(
            db_path=self.memory_db_path,
            config=self.config,
            cognitive_db=self.cognitive_db,
        )
        self.promotion_engine = PromotionEngine(
            db_path=self.memory_db_path,
            config=self.config,
            cognitive_db=self.cognitive_db,
        )

    async def decide(
        self,
        *,
        ticker: str,
        ref_date: str,
        cards: Sequence[AnalysisCard],
        debate_result: DebateResult | None,
        context: Mapping[str, Any] | None = None,
        portfolio_snapshot: Mapping[str, Any] | None = None,
    ) -> IntentTicket:
        """Return a validated CIO intent or a deterministic fallback on failure."""

        memory_snippets = self._load_memory_snippets(
            ticker=ticker,
            ref_date=ref_date,
            portfolio_snapshot=portfolio_snapshot,
        )
        playbook_match = self.promotion_engine.match_playbook(
            ticker=ticker,
            sector=str((portfolio_snapshot or {}).get("sector") or "other"),
            macro_context=(context or {}).get("macro_context"),
        )
        if playbook_match is not None and playbook_match.get("avg_alpha", 0) > 0.5:  # Hạ từ 2.0 xuống 0.5
            self.strategy_store.update_last_used(int(playbook_match["id"]))
            return self._playbook_ticket(
                ticker=ticker,
                playbook=playbook_match,
                portfolio_snapshot=portfolio_snapshot,
            )

        position_exists = self._position_exists(portfolio_snapshot, ticker)
        try:
            response = await call_llm(
                system_prompt=(
                    "Bạn là CIO của cognitive_trading. "
                    "Bạn phải trả về đúng một JSON object và không thêm gì khác. "
                    "Không được short selling. Chỉ dùng thông tin có sẵn tại hoặc trước ref_date."
                ),
                user_prompt=self._build_prompt(
                    ticker=ticker,
                    ref_date=ref_date,
                    cards=cards,
                    debate_result=debate_result,
                    context=context,
                    portfolio_snapshot=portfolio_snapshot,
                    memory_snippets=memory_snippets,
                ),
                model=self.config.cio_model,
                temperature=self.temperature,
                
                response_format={"type": "json_object"},
            )
            payload = self._extract_json_payload(response)
            payload = self._normalize_payload(
                payload=payload,
                ticker=ticker,
                portfolio_snapshot=portfolio_snapshot,
                position_exists=position_exists,
            )
            intent = IntentTicket.model_validate(payload)

            # Apply cooldown check
            if self._check_cooldown_violation(ticker=ticker, ref_date=ref_date, action=intent.action):
                return IntentTicket(
                    ticker=ticker,
                    action=Action.HOLD if position_exists else Action.PASS,
                    weight_pct=self._current_weight_pct(portfolio_snapshot, ticker) if position_exists else 0.0,
                    confidence=intent.confidence,
                    reasoning=f"Cooldown active: TRIMMING/SELL trong 1 ngày gần đây. Original intent: {intent.action.value}",
                    playbook_id=None,
                )

            return intent
        except (LLMError, ValidationError, ValueError, json.JSONDecodeError):
            return self._fallback_ticket(
                ticker=ticker,
                cards=cards,
                debate_result=debate_result,
                portfolio_snapshot=portfolio_snapshot,
            )

    def _build_prompt(
        self,
        *,
        ticker: str,
        ref_date: str,
        cards: Sequence[AnalysisCard],
        debate_result: DebateResult | None,
        context: Mapping[str, Any] | None,
        portfolio_snapshot: Mapping[str, Any] | None,
        memory_snippets: Sequence[Mapping[str, Any]],
    ) -> str:
        current_weight = self._current_weight_pct(portfolio_snapshot, ticker)
        total_nav = float((portfolio_snapshot or {}).get("total_nav", 1_000_000_000))
        cash = float((portfolio_snapshot or {}).get("cash", 0))
        cash_pct = (cash / total_nav * 100.0) if total_nav > 0 else 0.0
        
        bullish_count = sum(1 for c in cards if action_direction(c.action) == "buy")
        bearish_count = sum(1 for c in cards if action_direction(c.action) == "sell")
        
        return (
            "Hãy trả về JSON với các khóa ticker, action, weight_pct, confidence, reasoning, playbook_id.\n"
            "Các giá trị action hợp lệ: BUY, BUY_MORE, SELL, TRIMMING, HOLD, PASS.\n\n"
            "=== TARGET & CONVICTION RULES ===\n"
            f"TARGET: 12-15% per position (max {self.config.max_position_pct:.2f}%)\n"
            f"Current: {current_weight:.2f}% | Cash: {cash_pct:.1f}% | Analysts: {bullish_count}B/{bearish_count}S\n\n"
            "RULES:\n"
            f"- Nếu {bullish_count}/{len(cards)} analyst nghiêng BUY và không có red flags → ưu tiên BUY/BUY_MORE lên 12-15%\n"
            f"- Nếu cash > 40% ({cash_pct:.1f}%) và tín hiệu nghiêng BUY → ưu tiên giải ngân, không HOLD máy móc\n"
            "- Nếu 2+ analyst nghiêng BUY + catalyst rõ → BUY/BUY_MORE tối thiểu 8-10%\n"
            "- Mixed signals + có vị thế tốt → HOLD chỉ khi cash không cao và chưa có catalyst đủ mạnh\n"
            "- Chỉ PASS khi majority nghiêng SELL hoặc thiếu luận điểm hành động rõ ràng\n\n"
            "Không short. Với SELL: weight_pct=0. Với TRIMMING: weight_pct < current.\n"
            "Reasoning bằng tiếng Việt.\n\n"
            f"Ticker: {ticker} | Date: {ref_date}\n\n"
            f"Cards:\n{json.dumps(self._cards_payload(cards), ensure_ascii=False, indent=2)}\n\n"
            f"Debate:\n{json.dumps(self._debate_payload(debate_result), ensure_ascii=False, indent=2)}\n\n"
            f"Portfolio:\n{json.dumps(dict(portfolio_snapshot or {}), ensure_ascii=False, indent=2, default=str)}\n\n"
            f"Context:\n{json.dumps(dict(context or {}), ensure_ascii=False, indent=2, default=str)}\n\n"
            f"Memory:\n{json.dumps(list(memory_snippets), ensure_ascii=False, indent=2, default=str)}"
        )

    def _load_memory_snippets(
        self,
        *,
        ticker: str,
        ref_date: str,
        portfolio_snapshot: Mapping[str, Any] | None,
    ) -> list[dict[str, Any]]:
        sector = str((portfolio_snapshot or {}).get("sector") or "").strip().lower() or None
        snippets = self.episodic_store.find_similar(
            current_ref_date=ref_date,
            ticker=ticker,
            sector=sector,
            top_k=self.memory_limit,
        )
        compact = []
        for item in snippets:
            compact.append(
                {
                    "trade_date": item.get("trade_date"),
                    "ticker": item.get("ticker"),
                    "action": item.get("action"),
                    "entry_price": item.get("entry_price"),
                    "quantity": item.get("quantity"),
                    "alpha_vs_vn30": item.get("alpha_vs_vn30"),
                    "debate_summary": item.get("debate_summary"),
                    "cio_reasoning": item.get("cio_reasoning"),
                }
            )
        return compact

    def _check_cooldown_violation(
        self,
        *,
        ticker: str,
        ref_date: str,
        action: Action,
    ) -> bool:
        """Return True if action violates cooldown period (3 days after TRIMMING/SELL)."""
        from datetime import datetime, timedelta

        if action not in {Action.BUY, Action.BUY_MORE}:
            return False

        try:
            ref_dt = datetime.strptime(ref_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            return False

        recent_episodes = self.episodic_store.find_similar(
            current_ref_date=ref_date,
            ticker=ticker,
            sector=None,
            top_k=10,
        )

        for ep in recent_episodes:
            ep_action = str(ep.get("action") or "").strip().upper()
            if ep_action not in {"TRIMMING", "SELL"}:
                continue

            ep_date_str = str(ep.get("trade_date") or "")
            if not ep_date_str:
                continue

            try:
                ep_dt = datetime.strptime(ep_date_str, "%Y-%m-%d")
                days_since = (ref_dt - ep_dt).days
                if 0 < days_since < 1:  # Giảm từ 3 xuống 1 ngày
                    return True
            except (ValueError, TypeError):
                continue

        return False

    def _normalize_payload(
        self,
        *,
        payload: dict[str, Any],
        ticker: str,
        portfolio_snapshot: Mapping[str, Any] | None,
        position_exists: bool,
    ) -> dict[str, Any]:
        normalized = dict(payload)
        normalized["ticker"] = ticker.upper()

        action_text = str(normalized.get("action") or "PASS").strip().upper()
        if action_text == Action.BUY_MORE.value and not position_exists:
            action_text = Action.BUY.value
        if action_text in {Action.SELL.value, Action.TRIMMING.value} and not position_exists:
            action_text = Action.PASS.value
        if action_text in {"HOLD", Action.PASS.value} and not position_exists:
            action_text = Action.PASS.value
        normalized["action"] = action_text

        try:
            weight_pct = float(normalized.get("weight_pct", 0.0) or 0.0)
        except (TypeError, ValueError):
            weight_pct = 0.0
        current_weight = self._current_weight_pct(portfolio_snapshot, ticker)
        weight_pct = max(0.0, min(self.config.max_position_pct, weight_pct))
        if action_text == Action.SELL.value:
            weight_pct = 0.0
        elif action_text == Action.TRIMMING.value:
            weight_pct = min(weight_pct, current_weight)
        elif action_text in {"HOLD", Action.PASS.value}:
            weight_pct = current_weight
        elif action_text == Action.PASS.value:
            weight_pct = 0.0
        normalized["weight_pct"] = round(weight_pct, 4)

        try:
            confidence = float(normalized.get("confidence", 50.0) or 50.0)
        except (TypeError, ValueError):
            confidence = 50.0
        normalized["confidence"] = round(max(0.0, min(100.0, confidence)), 4)
        normalized["reasoning"] = str(normalized.get("reasoning") or "CIO đã tạo quyết định giao dịch.").strip()
        if "playbook_id" in normalized and normalized["playbook_id"] is not None:
            normalized["playbook_id"] = str(normalized["playbook_id"]).strip() or None
        return normalized

    def _playbook_ticket(
        self,
        *,
        ticker: str,
        playbook: Mapping[str, Any],
        portfolio_snapshot: Mapping[str, Any] | None,
    ) -> IntentTicket:
        current_weight = self._current_weight_pct(portfolio_snapshot, ticker)
        position_exists = current_weight > 0.0
        recommended_action = str(playbook.get("recommended_action") or "HOLD").strip().upper()
        if recommended_action == Action.BUY_MORE.value and not position_exists:
            recommended_action = Action.BUY.value
        if recommended_action in {Action.SELL.value, Action.TRIMMING.value} and not position_exists:
            recommended_action = Action.PASS.value
        if recommended_action in {"HOLD", Action.PASS.value} and not position_exists:
            recommended_action = Action.PASS.value

        if recommended_action == Action.BUY.value:
            weight_pct = self.config.max_position_pct
        elif recommended_action == Action.BUY_MORE.value:
            weight_pct = max(current_weight, self.config.max_position_pct)
        elif recommended_action == Action.TRIMMING.value:
            weight_pct = round(current_weight * 0.5, 4)
        elif recommended_action in {"HOLD", Action.PASS.value}:
            weight_pct = current_weight
        else:
            weight_pct = 0.0

        confidence = max(50.0, min(100.0, 50.0 + float(playbook.get("avg_alpha") or 0.0)))
        return IntentTicket(
            ticker=ticker,
            action=Action(recommended_action),
            weight_pct=round(max(0.0, min(self.config.max_position_pct, weight_pct)), 4),
            confidence=round(confidence, 4),
            reasoning=(
                "Khớp playbook fast-path. "
                f"Pattern={playbook.get('pattern_description')} | avg_alpha={playbook.get('avg_alpha')}"
            ),
            playbook_id=str(playbook.get("id")),
        )

    def _fallback_ticket(
        self,
        *,
        ticker: str,
        cards: Sequence[AnalysisCard],
        debate_result: DebateResult | None,
        portfolio_snapshot: Mapping[str, Any] | None,
    ) -> IntentTicket:
        current_weight = self._current_weight_pct(portfolio_snapshot, ticker)
        position_exists = current_weight > 0.0
        buy_score = 0.0
        sell_score = 0.0
        neutral_score = 0.0

        for card in cards:
            score = float(card.confidence_calibrated or card.confidence_raw)
            direction = action_direction(card.action)
            if direction == "buy":
                buy_score += score
            elif direction == "sell":
                sell_score += score
            else:
                neutral_score += score

        if debate_result is not None and debate_result.triggered:
            debate_bonus = float(debate_result.confidence) * 0.2
            if debate_result.winner == "bull":
                buy_score += debate_bonus
            elif debate_result.winner == "bear":
                sell_score += debate_bonus
            else:
                neutral_score += debate_bonus

        dominant_score = max(buy_score, sell_score, neutral_score)
        edge_vs_sell = buy_score - max(sell_score, neutral_score)
        edge_vs_buy = sell_score - max(buy_score, neutral_score)

        if buy_score == dominant_score and edge_vs_sell >= 8.0:
            action = Action.BUY_MORE if position_exists else Action.BUY
            target_weight = min(self.config.max_position_pct, max(current_weight, dominant_score / 100.0 * self.config.max_position_pct))
        elif sell_score == dominant_score and edge_vs_buy > 15.0 and position_exists:
            if dominant_score >= 70.0:
                action = Action.SELL
                target_weight = 0.0
            else:
                action = Action.TRIMMING
                target_weight = round(current_weight * 0.5, 4)
        else:
            action = Action.PASS
            target_weight = current_weight if position_exists else 0.0

        confidence = round(max(0.0, min(100.0, dominant_score if dominant_score > 0 else 50.0)), 4)
        reasoning = (
            "CIO đã dùng cơ chế dự phòng tất định dựa trên tổng điểm card đã hiệu chỉnh. "
            f"buy_score={buy_score:.2f}, sell_score={sell_score:.2f}, neutral_score={neutral_score:.2f}."
        )
        return IntentTicket(
            ticker=ticker,
            action=action,
            weight_pct=round(max(0.0, min(self.config.max_position_pct, target_weight)), 4),
            confidence=confidence,
            reasoning=reasoning,
            playbook_id=None,
        )

    @staticmethod
    def _extract_json_payload(text: str) -> dict[str, Any]:
        fenced = _JSON_FENCE_RE.search(text)
        if fenced:
            return json.loads(fenced.group(1))

        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)

        match = _JSON_OBJECT_RE.search(text)
        if not match:
            raise ValueError("No JSON object found in CIO response")
        return json.loads(match.group(1))

    @staticmethod
    def _cards_payload(cards: Sequence[AnalysisCard]) -> list[dict[str, Any]]:
        return [card.model_dump(mode="json", by_alias=True) for card in cards]

    @staticmethod
    def _debate_payload(debate_result: DebateResult | None) -> dict[str, Any] | None:
        if debate_result is None:
            return None
        return debate_result.to_dict()

    @staticmethod
    def _position_exists(portfolio_snapshot: Mapping[str, Any] | None, ticker: str) -> bool:
        if not portfolio_snapshot:
            return False
        positions = portfolio_snapshot.get("positions", {})
        return ticker.upper() in positions and float(positions[ticker.upper()].get("total_qty", 0) or 0) > 0

    @staticmethod
    def _current_weight_pct(portfolio_snapshot: Mapping[str, Any] | None, ticker: str) -> float:
        if not portfolio_snapshot:
            return 0.0
        current_weight = portfolio_snapshot.get("current_weight_pct")
        if current_weight is not None:
            try:
                return max(0.0, float(current_weight))
            except (TypeError, ValueError):
                return 0.0

        equity = float(portfolio_snapshot.get("equity") or 0.0)
        if equity <= 0:
            return 0.0
        positions = portfolio_snapshot.get("positions", {})
        ticker_view = positions.get(ticker.upper())
        if not isinstance(ticker_view, Mapping):
            return 0.0
        quantity = float(ticker_view.get("total_qty") or 0.0)
        price = float(portfolio_snapshot.get("current_price_vnd") or ticker_view.get("avg_price") or 0.0)
        if quantity <= 0 or price <= 0:
            return 0.0
        return round((quantity * price / equity) * 100.0, 4)


__all__ = ["CIOAgent"]
