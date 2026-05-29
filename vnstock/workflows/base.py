from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from vnstock.agents.macro_agent import MacroAgent
from vnstock.agents.news_agent import NewsAgent
from vnstock.agents.quant_agent import QuantAgent
from vnstock.agents.technical_agent import TechnicalAgent


@dataclass
class AgentOutput:
    agent_name: str
    raw_analysis: str
    signal: str = "neutral"
    confidence: float = 0.5
    evidence: List[str] = field(default_factory=list)
    key_data_points: Dict[str, Any] = field(default_factory=dict)
    token_count: int = 0


@dataclass
class WorkflowResult:
    workflow_name: str
    report: str
    impact_score: float
    risk_report: str
    debate_graph: Optional[dict] = None
    strategy: Optional[str] = None
    alpha_score: Optional[float] = None
    beta_score: Optional[float] = None
    llm_calls_count: int = 0
    total_tokens: int = 0


class SharedAgentPool:
    def __init__(self) -> None:
        self.macro = MacroAgent()
        self.news = NewsAgent()
        self.technical = TechnicalAgent()
        self.quant = QuantAgent()
        # financial agent is instantiated per call with parameters

    async def run_all(
        self,
        *,
        ticker: str,
        ref_date: str,
        year: str,
        quarter: str,
        llm_semaphore: asyncio.Semaphore,
        macro_cached: AgentOutput | None = None,
    ) -> Dict[str, AgentOutput]:
        # NOTE: Rate limiting is handled inside call_llm's TokenBucketRateLimiter.
        # No outer semaphore wrapping needed — avoids the double-semaphore problem.

        macro_raw = None
        if macro_cached is None:
            macro_raw = await self.macro.analyze(ref_date=ref_date)
        news_task = asyncio.create_task(self.news.analyze(ticker=ticker, ref_date=ref_date))
        tech_task = asyncio.create_task(self.technical.analyze(ticker=ticker, ref_date=ref_date))
        quant_task = asyncio.create_task(self.quant.analyze(ticker=ticker, ref_date=ref_date))

        from vnstock.agents.financial_agent import FinancialAgent

        fin_agent = FinancialAgent()
        fin_task = asyncio.create_task(fin_agent.analyze(ticker=ticker, year=year, quarter=quarter))

        try:
            news_raw, tech_raw, quant_raw, fin_raw = await asyncio.gather(
                news_task, tech_task, quant_task, fin_task
            )
        except Exception as exc:
            from vnstock.core.llm import LLMError

            raise LLMError(str(exc)) from exc

        def _force_impact(text: str) -> str:
            return (
                text
                if "Dự đoán ảnh hưởng" in text
                else (text.rstrip() + "\n\n⚠️ Agent không đưa ra dự đoán. Dự đoán ảnh hưởng: +0% [AUTO-INJECTED]")
            )

        macro_output = macro_cached or AgentOutput(agent_name="macro", raw_analysis=_force_impact(macro_raw))

        return {
            "macro": macro_output,
            "news": AgentOutput(agent_name="news", raw_analysis=_force_impact(news_raw)),
            "technical": AgentOutput(agent_name="technical", raw_analysis=tech_raw),
            "quant": AgentOutput(agent_name="quant", raw_analysis=quant_raw),
            "financial": AgentOutput(agent_name="financial", raw_analysis=_force_impact(fin_raw)),
        }
