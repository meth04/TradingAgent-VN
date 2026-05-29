"""Financial ReAct analyst for cognitive_trading using cached Markdown reports."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.swarm.base_analyst import BaseAnalyst, ToolSpec
from vnstock.agents.financial_agent import FinancialAgent

_MAX_REPORT_CHARS = 16_000


class FinancialAnalyst(BaseAnalyst):
    """Fundamental analyst that reads pre-generated financial report Markdown files."""

    agent_name = "financial"
    analysis_brief = "Đánh giá nền tảng cơ bản, chất lượng báo cáo và triển vọng kinh doanh từ hồ sơ tài chính."

    def __init__(self, *, config: CognitiveConfig | None = None) -> None:
        resolved_config = config or CognitiveConfig()
        super().__init__(
            model=resolved_config.financial_analyst_model,
            config=resolved_config,
        )
        self.financial_agent = FinancialAgent()

    def build_tools(
        self,
        *,
        ticker: str,
        ref_date: str,
        context: Mapping[str, Any],
    ) -> Sequence[ToolSpec]:
        financial_context = context.get("financial_context", {}) if isinstance(context, Mapping) else {}

        async def financial_reports(query: str) -> str:
            del query
            if isinstance(financial_context, Mapping) and financial_context.get("available"):
                excerpt = str(financial_context.get("excerpt") or "").strip()
                report_name = financial_context.get("report_name") or "unknown"
                truncated = financial_context.get("truncated")
                truncation_note = "\n\n[Báo cáo đã được cắt bớt để phù hợp ngân sách prompt.]" if truncated else ""
                return (
                    f"File báo cáo cache: {report_name}\n"
                    f"Mốc ngày báo cáo hợp lệ: <= {ref_date}\n\n"
                    f"{excerpt}{truncation_note}"
                )
            return await self._load_report_context(ticker=ticker, ref_date=ref_date)

        return (
            ToolSpec(
                name="financial_reports",
                description="Đọc báo cáo phân tích tài chính cache mới nhất có sẵn tại hoặc trước ref_date.",
                function=financial_reports,
            ),
        )

    async def _load_report_context(self, *, ticker: str, ref_date: str) -> str:
        return await self.financial_agent.get_report_context(
            ticker=ticker,
            ref_date=ref_date,
            max_chars=_MAX_REPORT_CHARS,
        )


__all__ = ["FinancialAnalyst"]
