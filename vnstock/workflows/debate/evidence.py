from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from vnstock.agents.prompting import BACKTEST_CONTEXT
from vnstock.workflows.base import AgentOutput


@dataclass
class Evidence:
    id: str
    source_agent: str
    claim: str
    direction: str  # "bullish" or "bearish"
    confidence: float
    data_points: list[str] = field(default_factory=list)
    data_quality: float = 0.5  # 1.0=quantitative, 0.5=qualitative, 0.2=no_data
    recency_days: float = 0.0

    @property
    def recency_score(self) -> float:
        if self.recency_days < 1:
            return 1.0
        if self.recency_days < 3:
            return 0.8
        return 0.6

    @property
    def source_reliability(self) -> float:
        return {
            "financial": 0.95,
            "quant": 0.90,
            "technical": 0.85,
            "macro": 0.70,
            "news": 0.65,
        }.get(self.source_agent, 0.5)

    @property
    def weight(self) -> float:
        """W(e) = 0.4*DataQuality + 0.3*Recency + 0.3*SourceReliability; scaled by confidence to 0-10."""
        w = 0.4 * self.data_quality + 0.3 * self.recency_score + 0.3 * self.source_reliability
        return round(w * self.confidence * 10, 2)


@dataclass
class Attack:
    attacker_id: str
    target_id: str
    reason: str
    strength: float  # 0.0-1.0


async def extract_evidence_from_agent_output(
    agent_output: AgentOutput, ref_date: str
) -> List[Evidence]:
    """
    Parse an agent's output into Evidence objects.
    Uses LLM to extract structured claims from raw_analysis text.
    Falls back to simple heuristic parsing if LLM unavailable.
    """
    
    _EVIDENCE_CACHE = getattr(extract_evidence_from_agent_output, "_cache", {})
    setattr(extract_evidence_from_agent_output, "_cache", _EVIDENCE_CACHE)
    
    cache_key = f"{agent_output.agent_name}_{hash(agent_output.raw_analysis)}_{ref_date}"
    if cache_key in _EVIDENCE_CACHE:
        return _EVIDENCE_CACHE[cache_key]

    def _is_valid_evidence_list(items: List[Evidence]) -> bool:
        return any(item.direction in {"bullish", "bearish"} and bool(item.claim.strip()) for item in items)

    evidences: List[Evidence] = []

    # Heuristic-first extraction: split paragraphs and pick directional cues
    def heuristic_parse(text: str) -> List[Evidence]:
        chunks = [c.strip() for c in text.split("\n") if c.strip()]
        results: List[Evidence] = []
        for idx, chunk in enumerate(chunks[:10]):
            direction = "bullish" if any(w in chunk.lower() for w in ["tăng", "mua", "tích cực", "bull"]) else "bearish" if any(w in chunk.lower() for w in ["giảm", "bán", "tiêu cực", "bear"]) else "neutral"
            if direction == "neutral":
                continue
            evid = Evidence(
                id=f"{agent_output.agent_name}_{idx}",
                source_agent=agent_output.agent_name,
                claim=chunk[:240],
                direction=direction,
                confidence=max(0.3, min(0.9, agent_output.confidence or 0.5)),
                data_points=[],
                data_quality=0.5,
                recency_days=0.0,
            )
            results.append(evid)
        return results

    evidences = heuristic_parse(agent_output.raw_analysis)

    if not _is_valid_evidence_list(evidences):
        try:
            from vnstock.core.llm import call_llm

            system_prompt = f"{BACKTEST_CONTEXT} Bạn là trợ lý phân tích, trích xuất luận cứ đầu tư."
            user_prompt = (
                "Tóm tắt 3-6 luận cứ với hướng (bullish/bearish) từ báo cáo agent. "
                "Mỗi luận cứ: id slug ngắn, claim, direction, confidence 0-1, list data_points.\n\n"
                f"Báo cáo agent {agent_output.agent_name}:\n{agent_output.raw_analysis}"
            )
            from config import models

            resp = await call_llm(
                system_prompt,
                user_prompt,
                temperature=0.2,
                model=models.t3_argument_model,
                
            )
            # Very light parse: expect bullet-like lines id|direction|claim
            parsed: List[Evidence] = []
            for idx, line in enumerate(resp.splitlines()):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 3:
                    continue
                evid_id, direction, claim = parts[:3]
                direction_norm = direction.lower()
                if direction_norm not in {"bullish", "bearish"}:
                    continue
                parsed.append(
                    Evidence(
                        id=evid_id or f"{agent_output.agent_name}_{idx}",
                        source_agent=agent_output.agent_name,
                        claim=claim,
                        direction=direction_norm,
                        confidence=max(0.3, min(1.0, agent_output.confidence or 0.5)),
                        data_points=parts[3:5] if len(parts) > 3 else [],
                        data_quality=1.0 if parts[3:] else 0.5,
                        recency_days=0.0,
                    )
                )
            if _is_valid_evidence_list(parsed):
                evidences = parsed
        except Exception:
            pass

    # Compute recency_days from ref_date vs today (approx)
    try:
        for ev in evidences:
            # Backtest context: evidence extracted at ref_date; avoid wall-clock penalty
            ev.recency_days = 0.0
    except Exception:
        pass

    _EVIDENCE_CACHE[cache_key] = evidences
    return evidences
