from __future__ import annotations

import json
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from vnstock.agents.prompting import BACKTEST_CONTEXT
from vnstock.core.llm import LLMError, call_llm
from vnstock.database.repo import DataRepository
from vnstock.engine.risk_engine import RiskLimits
from vnstock.workflows.base import AgentOutput
from vnstock.workflows.debate.autogen_debate import run_autogen_debate
from vnstock.workflows.utils import format_facts, safe_json_extract


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _relative_to_absolute_basket(
    weights: Dict[str, float],
    *,
    max_position_pct: float,
    max_total_pct: float,
    min_weight_pct: float,
) -> List[Dict[str, object]]:
    positive = {ticker: max(0.0, float(weight)) for ticker, weight in weights.items() if float(weight) > 0.0}
    if not positive or max_total_pct <= 0.0:
        return []

    max_relative = max(positive.values())
    if max_relative <= 0.0:
        return []

    scale = max_position_pct / max_relative
    absolute = {ticker: weight * scale for ticker, weight in positive.items()}
    total = sum(absolute.values())
    if total > max_total_pct and total > 0.0:
        factor = max_total_pct / total
        absolute = {ticker: weight * factor for ticker, weight in absolute.items()}

    basket: List[Dict[str, object]] = []
    for ticker, weight_pct in sorted(absolute.items(), key=lambda item: item[1], reverse=True):
        clipped = min(max_position_pct, max(0.0, weight_pct))
        if clipped < min_weight_pct:
            continue
        basket.append({"ticker": ticker, "weight_pct": round(clipped, 4)})
    return basket


class MarkowitzFrontierWorkflow:
    """True mean-variance optimizer with LLM qualitative validation."""

    def __init__(self, model: str | None = None) -> None:
        from config import models, strategy

        self.model = model or models.t4_cio_model
        self.risk_limits = RiskLimits()
        self.lookback_days = 120
        self.risk_free_rate = 0.03
        self.min_weight_pct = max(strategy.weight_increment_buffer_pct, 0.5)

    def _load_returns_frame(self, tickers: List[str], ref_date: str) -> pd.DataFrame:
        repo = DataRepository()
        ref_ts = pd.to_datetime(ref_date)
        try:
            series_map: Dict[str, pd.Series] = {}
            for ticker in sorted({ticker.strip().upper() for ticker in tickers if ticker}):
                df = repo.get_price_history(ticker, end_date=ref_ts, days=self.lookback_days + 1)
                if df.empty or len(df) < 20:
                    continue
                returns = (
                    df.sort_values("date")
                    .set_index("date")["close"]
                    .astype(float)
                    .pct_change()
                    .dropna()
                    .rename(ticker)
                )
                if len(returns) >= 20:
                    series_map[ticker] = returns
            if not series_map:
                return pd.DataFrame()
            if len(series_map) == 1:
                only = next(iter(series_map.values()))
                return only.to_frame().tail(self.lookback_days)
            return pd.concat(series_map.values(), axis=1, join="inner").dropna().tail(self.lookback_days)
        finally:
            repo.close()

    def _compute_efficient_weights(
        self,
        returns: pd.DataFrame,
    ) -> tuple[Dict[str, float], dict[str, object]]:
        if returns.empty or len(returns) < 20:
            return {}, {
                "observations": int(len(returns)),
                "tickers": list(returns.columns),
                "optimizer_success": False,
                "optimizer_message": "Insufficient return history for optimization.",
            }

        tickers = list(returns.columns)
        n_assets = len(tickers)
        mu = (returns.mean() * 252.0).to_numpy(dtype=float)
        cov = (returns.cov() * 252.0).to_numpy(dtype=float)
        cov = cov + np.eye(n_assets, dtype=float) * 1e-6

        if n_assets == 1:
            weights = np.array([1.0], dtype=float)
            metrics = self._portfolio_metrics(weights, mu, cov)
            return {tickers[0]: 1.0}, {
                "observations": int(len(returns)),
                "tickers": tickers,
                "optimizer_success": True,
                "optimizer_message": "Single asset basket.",
                **metrics,
            }

        def neg_sharpe(weights: np.ndarray) -> float:
            port_vol = float(np.sqrt(max(weights @ cov @ weights, 0.0)))
            if port_vol <= 1e-12:
                return 1e6
            port_ret = float(weights @ mu)
            return -((port_ret - self.risk_free_rate) / port_vol)

        x0 = np.ones(n_assets, dtype=float) / n_assets
        bounds = [(0.0, 1.0)] * n_assets
        constraints = [{"type": "eq", "fun": lambda weights: np.sum(weights) - 1.0}]
        result = minimize(
            neg_sharpe,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
        )

        raw_weights = np.array(result.x if result.success else x0, dtype=float)
        raw_weights = np.clip(raw_weights, 0.0, None)
        total = float(raw_weights.sum())
        if total <= 0.0:
            raw_weights = x0
            total = float(raw_weights.sum())
        weights = raw_weights / total
        metrics = self._portfolio_metrics(weights, mu, cov)
        return {
            ticker: float(weight) for ticker, weight in zip(tickers, weights, strict=False) if weight > 0.0
        }, {
            "observations": int(len(returns)),
            "tickers": tickers,
            "optimizer_success": bool(result.success),
            "optimizer_message": str(result.message),
            **metrics,
        }

    def _portfolio_metrics(
        self,
        weights: np.ndarray,
        mu: np.ndarray,
        cov: np.ndarray,
    ) -> dict[str, float]:
        annual_return = float(weights @ mu)
        annual_volatility = float(np.sqrt(max(weights @ cov @ weights, 0.0)))
        sharpe = 0.0
        if annual_volatility > 1e-12:
            sharpe = (annual_return - self.risk_free_rate) / annual_volatility
        return {
            "annual_return": round(annual_return, 6),
            "annual_volatility": round(annual_volatility, 6),
            "sharpe_ratio": round(sharpe, 6),
        }

    def _build_optimized_basket(
        self,
        *,
        relative_weights: Dict[str, float],
        current_weights: Dict[str, float],
        portfolio_snapshot: Dict[str, object],
    ) -> List[Dict[str, object]]:
        equity = _safe_float(portfolio_snapshot.get("equity"), 0.0)
        cash = _safe_float(portfolio_snapshot.get("cash"), 0.0)
        invested_pct = 0.0
        if equity > 0.0:
            invested_pct = max(0.0, min(100.0, (equity - cash) / equity * 100.0))
        current_basket_weight = sum(
            max(0.0, _safe_float(current_weights.get(ticker), 0.0)) for ticker in relative_weights
        )
        available_capacity = max(0.0, self.risk_limits.max_portfolio_invested_pct - invested_pct)
        basket_capacity = min(
            self.risk_limits.max_portfolio_invested_pct,
            current_basket_weight + available_capacity,
        )
        return _relative_to_absolute_basket(
            relative_weights,
            max_position_pct=self.risk_limits.max_position_pct,
            max_total_pct=basket_capacity,
            min_weight_pct=self.min_weight_pct,
        )

    async def run(
        self,
        *,
        tickers: List[str],
        ref_date: str,
        agent_outputs_map: Dict[str, Dict[str, AgentOutput]],
        current_weights: Dict[str, float],
        portfolio_snapshot: Dict[str, object],
        llm_semaphore=None,
    ) -> Dict[str, object]:
        facts_list: List[str] = []
        for ticker in tickers:
            facts_list.append(f"## {ticker}\n{format_facts(agent_outputs_map.get(ticker, {}))}")
        facts = "\n\n".join(facts_list)

        from config import models

        debate_res = await run_autogen_debate(
            ticker=",".join(tickers),
            ref_date=ref_date,
            agent_outputs={f"{t}_{k}": v for t in tickers for k, v in agent_outputs_map.get(t, {}).items()},
            llm_semaphore=llm_semaphore,
            model=models.t3_debate_model,
            rounds=2,
            preformatted_facts=facts,
        )
        transcript = debate_res["transcript"]
        final_score = debate_res["final_score"]

        returns = self._load_returns_frame(tickers, ref_date)
        relative_weights, optimizer_summary = self._compute_efficient_weights(returns)
        optimized_basket = self._build_optimized_basket(
            relative_weights=relative_weights,
            current_weights=current_weights,
            portfolio_snapshot=portfolio_snapshot,
        )
        optimizer_summary["proposed_basket"] = optimized_basket

        if not optimized_basket:
            decision = {
                "action": "PASS",
                "basket": [],
                "reasoning": "Fallback: optimizer did not produce a valid basket.",
                "optimizer": optimizer_summary,
                "final_score": final_score,
                "verdict": debate_res.get("verdict"),
                "net_score": debate_res.get("net_score"),
            }
            return {
                "transcript": transcript,
                "decision": decision,
                "raw_decision": json.dumps(decision, ensure_ascii=False),
            }

        cio_system = (
            f"{BACKTEST_CONTEXT} "
            "Bạn là CIO phân bổ danh mục của quỹ multi-agent theo khung tối ưu hóa Markowitz. Hãy suy luận hoàn toàn bằng tiếng Việt, chuyên nghiệp và ngắn gọn:\n"
            "1) Phân tích mức đồng thuận và bất đồng giữa 5 chuyên gia (Macro, News, Technical, Quant, Financial).\n"
            "2) Tổng hợp luận điểm tích cực, tiêu cực và chất lượng bằng chứng.\n"
            "3) Rà soát basket tối ưu đã được cung cấp cùng các chỉ số expected return, volatility, Sharpe ratio.\n"
            "4) Đối chiếu basket tối ưu với trạng thái danh mục hiện tại và chi phí tái cân bằng.\n"
            "5) Phê duyệt basket hoặc từ chối một cách định tính. Không tự tính lại trọng số. Chỉ trả JSON hợp lệ."
        )
        cur_weights_str = ", ".join([f"{t}:{current_weights.get(t, 0.0):.2f}%" for t in tickers])
        
        # Calculate average P&L across basket
        avg_pnl = 0.0
        pnl_count = 0
        for ticker in tickers:
            snapshot = portfolio_snapshot.get(ticker, {})
            if isinstance(snapshot, dict):
                pnl = snapshot.get('unrealized_pnl_pct', 0.0)
                if pnl != 0.0:
                    avg_pnl += pnl
                    pnl_count += 1
        avg_pnl = avg_pnl / pnl_count if pnl_count > 0 else 0.0
        
        cio_user = (
            "Bạn là quỹ đầu tư chiến lược, không phải day-trader.\n"
            "Hành động hợp lệ: BASKET_CREATED, PASS, IGNORE.\n"
            "Không short. Không tự sinh basket mới. Chỉ được phê duyệt basket tối ưu đã cung cấp hoặc từ chối nó.\n\n"
            "=== TAKE-PROFIT RULES (ƯU TIÊN CAO) ===\n"
            f"P&L trung bình basket: {avg_pnl:.2f}%\n"
            "- Nếu avg P&L > +15% VÀ (verdict bearish HOẶC final_score < 0) → PASS (không rebalance, chờ chốt lời)\n"
            "- Nếu avg P&L > +20% → PASS (giữ nguyên để chốt lời)\n"
            "- Nếu avg P&L < -5% VÀ verdict bearish → PASS (chờ cắt lỗ riêng lẻ)\n"
            "- Nếu avg P&L trong khoảng -5% đến +15% → Xét basket optimization\n\n"
            "Cấu trúc reasoning bắt buộc:\n"
            "  - Đồng thuận: [Điểm đồng thuận giữa các agent]\n"
            "  - Bất đồng: [Điểm xung đột và cách xử lý]\n"
            "  - Bằng chứng: [Bằng chứng chính hỗ trợ quyết định]\n"
            "  - P&L Check: [Kiểm tra take-profit cho basket]\n"
            "  - Chất lượng tối ưu hóa: [Đánh giá chất lượng basket tối ưu]\n"
            "  - Quyết định: [Quyết định cuối cùng và lý do]\n"
            "Schema: {\"action\": \"BASKET_CREATED\"|\"PASS\"|\"IGNORE\", \"reasoning\": <string>}.\n"
            f"Tỷ trọng hiện tại: {cur_weights_str}. Portfolio snapshot: {portfolio_snapshot}.\n"
            f"Chẩn đoán optimizer: {optimizer_summary}.\n"
            f"Final_score={final_score:.3f}."
        )

        try:
            decision_text = await call_llm(
                cio_system,
                f"Transcript:\n{transcript}\n\n{cio_user}",
                model=models.t4_cio_model,
                
                response_format={"type": "json_object"},
            )
        except LLMError as exc:
            return {
                "transcript": transcript,
                "decision": {
                    "action": "PASS",
                    "basket": [],
                    "_llm_error": True,
                    "error": str(exc),
                    "optimizer": optimizer_summary,
                },
                "raw_decision": str(exc),
            }

        parsed, raw = safe_json_extract(decision_text)
        decision = {
            "action": "PASS",
            "basket": [],
            "reasoning": "Fallback: invalid JSON from CIO.",
            "optimizer": optimizer_summary,
        }
        if isinstance(parsed, dict):
            action = str(parsed.get("action", "")).upper()
            reasoning = str(parsed.get("reasoning", "") or "")
            # HOLD bug fix: Markowitz doesn't use HOLD, but ensure PASS with no positions is handled
            if action == "BASKET_CREATED":
                decision = {
                    "action": "BASKET_CREATED",
                    "basket": optimized_basket,
                    "reasoning": reasoning,
                    "optimizer": optimizer_summary,
                }
            elif action in {"PASS", "IGNORE"}:
                decision = {
                    "action": action,
                    "basket": [],
                    "reasoning": reasoning,
                    "optimizer": optimizer_summary,
                }
        decision["final_score"] = final_score
        decision["verdict"] = debate_res.get("verdict")
        decision["net_score"] = debate_res.get("net_score")
        return {
            "transcript": transcript,
            "decision": decision,
            "raw_decision": raw,
        }
