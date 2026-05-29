"""Bull/Bear/Judge debate orchestration for cognitive_trading decisions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.decision.debate_trigger import action_direction
from cognitive_trading.governance.schemas import AnalysisCard
from vnstock.agents.prompting import Action
from vnstock.core.llm import LLMError, call_llm
from vnstock.workflows.base import AgentOutput
from vnstock.workflows.debate.autogen_debate import run_autogen_debate

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"(\{[\s\S]*\})")


@dataclass(frozen=True, slots=True)
class DebateTurn:
    """Single turn in the Bull/Bear debate transcript."""

    speaker: str
    round_number: int
    stance: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker": self.speaker,
            "round_number": self.round_number,
            "stance": self.stance,
            "content": self.content,
        }


@dataclass(frozen=True, slots=True)
class DebateResult:
    """Structured debate output consumed by the CIO and daily reporter."""

    ticker: str
    ref_date: str
    triggered: bool
    verdict: str
    winner: str
    confidence: float
    summary: str
    judge_rationale: str
    transcript: tuple[DebateTurn, ...] = ()
    llm_error: str | None = None

    @classmethod
    def skipped(cls, *, ticker: str, ref_date: str, reason: str) -> "DebateResult":
        return cls(
            ticker=ticker,
            ref_date=ref_date,
            triggered=False,
            verdict="neutral",
            winner="none",
            confidence=0.0,
            summary=reason,
            judge_rationale=reason,
            transcript=(),
            llm_error=None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "ref_date": self.ref_date,
            "triggered": self.triggered,
            "verdict": self.verdict,
            "winner": self.winner,
            "confidence": self.confidence,
            "summary": self.summary,
            "judge_rationale": self.judge_rationale,
            "transcript": [turn.to_dict() for turn in self.transcript],
            "llm_error": self.llm_error,
        }


@dataclass(slots=True)
class DebateEngine:
    """Run a lightweight Bull/Bear/Judge debate when analyst cards conflict."""

    config: CognitiveConfig = CognitiveConfig()
    rounds: int = 3
    temperature: float = 0.2

    async def debate(
        self,
        *,
        ticker: str,
        ref_date: str,
        cards: Sequence[AnalysisCard],
        context: Mapping[str, Any] | None = None,
        portfolio_snapshot: Mapping[str, Any] | None = None,
    ) -> DebateResult:
        """Return a structured debate result or a flagged deterministic fallback."""

        transcript: list[DebateTurn] = []
        try:
            agent_outputs = self._cards_to_agent_outputs(cards)
            autogen_result = await run_autogen_debate(
                ticker=ticker,
                ref_date=ref_date,
                agent_outputs=agent_outputs,
                model=self.config.debate_model,
                rounds=self.rounds,
            )
            transcript = self._autogen_transcript_to_turns(str(autogen_result.get("transcript") or ""))
            if str(autogen_result.get("transcript") or "").startswith("[DEBATE_FALLBACK]"):
                raise LLMError(str(autogen_result.get("transcript") or "AutoGen debate failed"))
            verdict = self._normalize_autogen_verdict(autogen_result.get("verdict"))
            winner = self._normalize_winner(None, verdict)
            confidence = self._normalize_confidence(float(autogen_result.get("final_score") or 0.5) * 100.0)
            summary = str(autogen_result.get("summary_vi") or "Tranh luận AutoGen đã hoàn tất.").strip()
            rationale = summary
            return DebateResult(
                ticker=ticker,
                ref_date=ref_date,
                triggered=True,
                verdict=verdict,
                winner=winner,
                confidence=confidence,
                summary=summary,
                judge_rationale=rationale,
                transcript=tuple(transcript),
            )
        except (LLMError, ValueError, json.JSONDecodeError) as exc:
            return self._fallback_result(
                ticker=ticker,
                ref_date=ref_date,
                cards=cards,
                transcript=transcript,
                error_message=str(exc),
            )

    async def _run_side(
        self,
        *,
        side: str,
        ticker: str,
        ref_date: str,
        cards: Sequence[AnalysisCard],
        transcript: Sequence[DebateTurn],
        context: Mapping[str, Any] | None,
        portfolio_snapshot: Mapping[str, Any] | None,
        round_number: int,
    ) -> str:
        system_prompt = (
            f"Bạn là bên tranh luận {side.upper()} của cognitive_trading. "
            "Chỉ dùng analyst cards, portfolio snapshot và ngữ cảnh an toàn theo ref_date đã được cung cấp. "
            "Tuyệt đối không dùng thông tin tương lai. Trả lời ngắn gọn, có bằng chứng và hoàn toàn bằng tiếng Việt."
        )
        user_prompt = (
            f"Ticker: {ticker}\n"
            f"ref_date: {ref_date}\n"
            f"Vòng: {round_number}\n"
            f"Phe: {side}\n\n"
            f"Cards:\n{json.dumps(self._cards_payload(cards), ensure_ascii=False, indent=2)}\n\n"
            f"Ngữ cảnh:\n{json.dumps(dict(context or {}), ensure_ascii=False, indent=2, default=str)}\n\n"
            "Ảnh chụp danh mục:\n"
            f"{json.dumps(dict(portfolio_snapshot or {}), ensure_ascii=False, indent=2, default=str)}\n\n"
            f"Biên bản trước đó:\n{self._transcript_text(transcript) or '(không có)'}\n\n"
            f"Hãy lập luận cho phe {side.upper()} bằng 2-4 gạch đầu dòng hoặc câu ngắn, hoàn toàn bằng tiếng Việt."
        )
        try:
            response = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.config.debate_model,
                temperature=self.temperature,
                
            )
        except LLMError as exc:
            raise LLMError(f"{side} debate turn failed: {exc}") from exc
        return response.strip()

    async def _judge(
        self,
        *,
        ticker: str,
        ref_date: str,
        cards: Sequence[AnalysisCard],
        transcript: Sequence[DebateTurn],
        context: Mapping[str, Any] | None,
        portfolio_snapshot: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        system_prompt = (
            "Bạn là giám khảo tranh luận của cognitive_trading. "
            "Hãy trả về đúng một JSON object và không thêm gì khác. "
            "Chỉ dùng bằng chứng đã được cung cấp tại hoặc trước ref_date."
        )
        user_prompt = (
            "Trả về JSON với các khóa verdict, winner, confidence, summary, judge_rationale.\n"
            "verdict phải là BUY, SELL hoặc HOLD.\n"
            "winner phải là BULL, BEAR hoặc TIE.\n"
            "confidence phải nằm trong 0-100.\n"
            "summary và judge_rationale phải viết bằng tiếng Việt.\n\n"
            f"Ticker: {ticker}\n"
            f"ref_date: {ref_date}\n\n"
            f"Cards:\n{json.dumps(self._cards_payload(cards), ensure_ascii=False, indent=2)}\n\n"
            f"Ngữ cảnh:\n{json.dumps(dict(context or {}), ensure_ascii=False, indent=2, default=str)}\n\n"
            "Ảnh chụp danh mục:\n"
            f"{json.dumps(dict(portfolio_snapshot or {}), ensure_ascii=False, indent=2, default=str)}\n\n"
            f"Biên bản tranh luận:\n{self._transcript_text(transcript)}"
        )
        try:
            response = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.config.debate_model,
                temperature=0.0,
                
                response_format={"type": "json_object"},
            )
        except LLMError as exc:
            raise LLMError(f"debate judge failed: {exc}") from exc
        return self._extract_json_payload(response)

    def _fallback_result(
        self,
        *,
        ticker: str,
        ref_date: str,
        cards: Sequence[AnalysisCard],
        transcript: Sequence[DebateTurn],
        error_message: str,
    ) -> DebateResult:
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

        if buy_score > sell_score and buy_score >= neutral_score:
            verdict = "buy"
            winner = "bull"
        elif sell_score > buy_score and sell_score >= neutral_score:
            verdict = "sell"
            winner = "bear"
        else:
            verdict = "neutral"
            winner = "tie"

        total = max(1.0, buy_score + sell_score + neutral_score)
        confidence = round((max(buy_score, sell_score, neutral_score) / total) * 100.0, 4)
        summary = (
            "Hệ thống đã dùng cơ chế tổng hợp card mang tính tất định vì phần tranh luận LLM bị lỗi. "
            f"buy_score={buy_score:.2f}, sell_score={sell_score:.2f}, neutral_score={neutral_score:.2f}."
        )
        return DebateResult(
            ticker=ticker,
            ref_date=ref_date,
            triggered=True,
            verdict=verdict,
            winner=winner,
            confidence=confidence,
            summary=summary,
            judge_rationale=summary,
            transcript=tuple(transcript),
            llm_error=error_message,
        )

    @staticmethod
    def _cards_payload(cards: Sequence[AnalysisCard]) -> list[dict[str, Any]]:
        return [
            {
                "agent_name": card.agent_name,
                "action": card.action.value,
                "confidence_raw": card.confidence_raw,
                "confidence_calibrated": card.confidence_calibrated,
                "upside_pct": card.upside_pct,
                "downside_pct": card.downside_pct,
                "reasoning": card.reasoning,
                "evidence_ids": list(card.evidence_ids),
            }
            for card in cards
        ]

    @staticmethod
    def _transcript_text(transcript: Sequence[DebateTurn]) -> str:
        return "\n\n".join(
            f"Vòng {turn.round_number} | {turn.speaker.upper()}:\n{turn.content}"
            for turn in transcript
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
            raise ValueError("No JSON object found in judge response")
        return json.loads(match.group(1))

    @staticmethod
    def _normalize_verdict(value: Any) -> str:
        normalized = str(value or "HOLD").strip().upper()
        if normalized in {Action.BUY.value, Action.BUY_MORE.value}:
            return "buy"
        if normalized in {Action.SELL.value, Action.TRIMMING.value}:
            return "sell"
        return "neutral"

    @staticmethod
    def _normalize_autogen_verdict(value: Any) -> str:
        normalized = str(value or "neutral").strip().lower()
        if "bull" in normalized:
            return "buy"
        if "bear" in normalized:
            return "sell"
        return "neutral"

    @staticmethod
    def _normalize_winner(value: Any, verdict: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"bull", "bear", "tie"}:
            return normalized
        if verdict == "buy":
            return "bull"
        if verdict == "sell":
            return "bear"
        return "tie"

    @staticmethod
    def _normalize_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 50.0
        return round(max(0.0, min(100.0, confidence)), 4)

    @staticmethod
    def _cards_to_agent_outputs(cards: Sequence[AnalysisCard]) -> dict[str, AgentOutput]:
        return {
            card.agent_name: AgentOutput(
                agent_name=card.agent_name,
                raw_analysis=card.reasoning,
                confidence=float((card.confidence_calibrated or card.confidence_raw) / 100.0),
                evidence=list(card.evidence_ids),
                key_data_points={
                    "action": card.action.value,
                    "upside_pct": card.upside_pct,
                    "downside_pct": card.downside_pct,
                },
            )
            for card in cards
        }

    @staticmethod
    def _autogen_transcript_to_turns(transcript_text: str) -> list[DebateTurn]:
        if not transcript_text.strip():
            return []
        turns: list[DebateTurn] = []
        round_number = 0
        for line in transcript_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            speaker = "judge"
            stance = "neutral"
            lower = stripped.lower()
            if lower.startswith("[bull]") or lower.startswith("bull"):
                speaker = "bull"
                stance = "buy"
                if speaker == "bull":
                    round_number += 1
            elif lower.startswith("[bear]") or lower.startswith("bear"):
                speaker = "bear"
                stance = "sell"
            turns.append(DebateTurn(speaker=speaker, round_number=max(1, round_number or 1), stance=stance, content=stripped))
        return turns


__all__ = ["DebateEngine", "DebateResult", "DebateTurn"]
