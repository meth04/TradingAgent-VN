from __future__ import annotations

import asyncio
from datetime import date

from vnstock.agents.financial_agent import get_cached_financial_report


class FinancialRAGTool:
    @staticmethod
    async def analyze_report_async(
        query: str,
        ticker: str | None = None,
        year: str | int | None = None,
        quarter: str | int | None = None,
        ref_date: str | None = None,
    ) -> str:
        del query
        if not ticker:
            return "Cần cung cấp ticker để đọc báo cáo tài chính cached."

        if ref_date is not None:
            report = get_cached_financial_report(ticker, ref_date=ref_date)
        elif year is not None and quarter is not None:
            report = get_cached_financial_report(ticker, year=year, quarter=quarter)
        else:
            report = get_cached_financial_report(ticker, ref_date=date.today().isoformat())

        if report is None:
            return f"Không tìm thấy báo cáo tài chính cached cho {ticker.upper()}."
        return report.content

    @staticmethod
    def analyze_report_sync(query: str, ticker: str | None = None) -> str:
        return asyncio.run(FinancialRAGTool.analyze_report_async(query, ticker))
