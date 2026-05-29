from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from config import models, paths
from vnstock.agents.prompting import BACKTEST_CONTEXT, TEXT_COT_PREFIX
from vnstock.core.llm import LLMError, call_llm


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_REPORT_MAX_CHARS = 16_000
_CONTEXT_REPORT_MAX_CHARS = 4_000


def _project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


ANALYSIS_ROOT = _project_path(paths.analysis_reports_dir)


@dataclass(frozen=True)
class CachedFinancialReport:
    ticker: str
    year: int
    quarter: int
    path: Path
    content: str


def normalize_financial_quarter(quarter: str | int) -> str:
    quarter_text = str(quarter).strip().upper()
    if quarter_text.startswith("Q"):
        quarter_text = quarter_text[1:]
    if quarter_text not in {"1", "2", "3", "4"}:
        raise ValueError(f"Invalid quarter: {quarter}")
    return f"Q{quarter_text}"


def _quarter_number(quarter: str | int) -> int:
    return int(normalize_financial_quarter(quarter)[1:])


def _parse_ref_date(ref_date: str | date | datetime) -> datetime:
    if isinstance(ref_date, datetime):
        return ref_date
    if isinstance(ref_date, date):
        return datetime.combine(ref_date, datetime.min.time())
    return datetime.fromisoformat(str(ref_date))


def _iterate_quarters_backward(
    start_year: int,
    start_quarter: int,
) -> Iterator[tuple[int, int]]:
    year = start_year
    quarter = start_quarter
    while year >= 2000:
        yield year, quarter
        if quarter == 1:
            year -= 1
            quarter = 4
        else:
            quarter -= 1


def _latest_allowed_quarter(ref_date: str | date | datetime) -> tuple[int, int]:
    from vnstock.tools.backtest.engine import get_latest_financial_quarter

    return get_latest_financial_quarter(_parse_ref_date(ref_date))


def _build_cached_report(
    *,
    ticker: str,
    year: int,
    quarter: int,
    path: Path,
) -> CachedFinancialReport | None:
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    return CachedFinancialReport(
        ticker=ticker.upper(),
        year=year,
        quarter=quarter,
        path=path,
        content=content,
    )


def get_exact_cached_financial_report(
    ticker: str,
    *,
    year: str | int,
    quarter: str | int,
) -> CachedFinancialReport | None:
    ticker_upper = ticker.upper()
    year_int = int(year)
    quarter_int = _quarter_number(quarter)
    report_path = ANALYSIS_ROOT / f"{ticker_upper}_{year_int}_Q{quarter_int}.md"
    return _build_cached_report(
        ticker=ticker_upper,
        year=year_int,
        quarter=quarter_int,
        path=report_path,
    )


def get_cached_financial_report(
    ticker: str,
    *,
    ref_date: str | date | datetime | None = None,
    year: str | int | None = None,
    quarter: str | int | None = None,
) -> CachedFinancialReport | None:
    if ref_date is not None:
        start_year, start_quarter = _latest_allowed_quarter(ref_date)
    elif year is not None and quarter is not None:
        start_year = int(year)
        start_quarter = _quarter_number(quarter)
    else:
        raise ValueError("Provide ref_date or year and quarter.")

    ticker_upper = ticker.upper()
    for candidate_year, candidate_quarter in _iterate_quarters_backward(
        start_year,
        start_quarter,
    ):
        report_path = ANALYSIS_ROOT / f"{ticker_upper}_{candidate_year}_Q{candidate_quarter}.md"
        report = _build_cached_report(
            ticker=ticker_upper,
            year=candidate_year,
            quarter=candidate_quarter,
            path=report_path,
        )
        if report is not None:
            return report
    return None


def _clip_report(content: str, max_chars: int) -> tuple[str, bool]:
    cleaned = content.strip()
    excerpt = cleaned[:max_chars]
    return excerpt, len(cleaned) > max_chars


def _ensure_impact_line(text: str) -> str:
    if "Dự đoán ảnh hưởng" in text:
        return text
    return text.rstrip() + "\n\nDự đoán ảnh hưởng: +0%"


class FinancialAgent:
    """Workflow-facing financial analyst backed by cached markdown reports."""

    async def _generate_report(self, *, ticker: str, year: str | int, quarter: str | int) -> CachedFinancialReport | None:
        quarter_label = normalize_financial_quarter(quarter)
        try:
            from vnstock.agents.financial_analysis import (
                FinancialAnalysisError,
                generate_financial_report,
            )

            artifact = await generate_financial_report(ticker.upper(), str(year), quarter_label)
        except FinancialAnalysisError:
            return None

        return CachedFinancialReport(
            ticker=ticker.upper(),
            year=int(artifact.year),
            quarter=_quarter_number(artifact.quarter),
            path=artifact.path,
            content=artifact.content,
        )

    async def _resolve_report(
        self,
        *,
        ticker: str,
        year: str | int | None = None,
        quarter: str | int | None = None,
        ref_date: str | date | datetime | None = None,
    ) -> CachedFinancialReport | None:
        if ref_date is not None:
            report = get_cached_financial_report(ticker, ref_date=ref_date)
            if report is not None:
                return report
            latest_year, latest_quarter = _latest_allowed_quarter(ref_date)
            return await self._generate_report(
                ticker=ticker,
                year=str(latest_year),
                quarter=f"Q{latest_quarter}",
            )

        if year is None or quarter is None:
            raise ValueError("Provide ref_date or year and quarter.")

        report = get_exact_cached_financial_report(ticker, year=year, quarter=quarter)
        if report is not None:
            return report
        return await self._generate_report(ticker=ticker, year=year, quarter=quarter)

    async def get_financial_context(
        self,
        *,
        ticker: str,
        ref_date: str,
        max_chars: int = _CONTEXT_REPORT_MAX_CHARS,
    ) -> dict[str, Any]:
        report = await self._resolve_report(ticker=ticker, ref_date=ref_date)
        if report is None:
            return {
                "available": False,
                "source": "cached_financial_report",
                "reason": f"Không tìm thấy báo cáo tài chính cache cho {ticker} tại hoặc trước {ref_date}.",
            }

        content = report.content.strip()
        if not content:
            return {
                "available": False,
                "source": "cached_financial_report",
                "reason": f"Báo cáo tài chính cache {report.path.name} đang rỗng.",
                "report_name": report.path.name,
                "year": int(report.year),
                "quarter": f"Q{int(report.quarter)}",
            }

        excerpt, truncated = _clip_report(content, max_chars)
        return {
            "available": True,
            "source": "cached_financial_report",
            "report_name": report.path.name,
            "report_path": str(report.path),
            "year": int(report.year),
            "quarter": f"Q{int(report.quarter)}",
            "excerpt": excerpt,
            "truncated": truncated,
            "valid_at_or_before": ref_date,
        }

    async def get_report_context(
        self,
        *,
        ticker: str,
        ref_date: str,
        max_chars: int = _WORKFLOW_REPORT_MAX_CHARS,
    ) -> str:
        report = await self._resolve_report(ticker=ticker, ref_date=ref_date)
        if report is None:
            return (
                f"Không tìm thấy báo cáo tài chính cache cho {ticker} tại hoặc trước {ref_date}. "
                "Hãy chỉ dùng ngữ cảnh giá/tin tức/vĩ mô và giữ quan điểm thận trọng."
            )

        content = report.content.strip()
        if not content:
            return (
                f"Báo cáo tài chính cache {report.path.name} đang rỗng. "
                "Hãy chỉ dùng ngữ cảnh ngoài tài chính và giữ quan điểm thận trọng."
            )

        clipped, truncated = _clip_report(content, max_chars)
        truncation_note = "\n\n[Báo cáo đã được cắt bớt để phù hợp ngân sách prompt.]" if truncated else ""
        return (
            f"File báo cáo cache: {report.path.name}\n"
            f"Mốc ngày báo cáo hợp lệ: <= {ref_date}\n\n"
            f"{clipped}{truncation_note}"
        )

    async def analyze(self, *, ticker: str, year: str, quarter: str) -> str:
        report = await self._resolve_report(ticker=ticker, year=year, quarter=quarter)
        quarter_label = normalize_financial_quarter(quarter)
        if report is None:
            return _ensure_impact_line(
                f"Không thể lấy hoặc tạo báo cáo phân tích tài chính cho {ticker.upper()} {quarter_label}/{year}."
            )

        report_content = report.content.strip()
        if not report_content:
            return _ensure_impact_line(
                f"Báo cáo phân tích tài chính cho {ticker.upper()} {quarter_label}/{year} đang rỗng."
            )

        clipped_report, truncated = _clip_report(report_content, _WORKFLOW_REPORT_MAX_CHARS)
        truncation_note = "\n\n[Lưu ý: Báo cáo nguồn đã được cắt bớt để phù hợp ngân sách prompt.]" if truncated else ""

        system_prompt = (
            f"{BACKTEST_CONTEXT} "
            f"{TEXT_COT_PREFIX} "
            "Bạn là Chuyên gia Phân tích Tài chính doanh nghiệp tại hedge fund. "
            "Hãy đọc báo cáo phân tích tài chính đã được chuẩn bị sẵn, sau đó đánh giá tác động kinh tế lên mã cổ phiếu. "
            "Không chép lại nguyên văn báo cáo. Chỉ rút ra luận điểm quan trọng, có tính đầu tư."
        )
        user_prompt = f"""
        Mã cổ phiếu: {ticker.upper()}
        Kỳ báo cáo cần đánh giá: {quarter_label}/{year}

        Dưới đây là báo cáo phân tích tài chính đã cache sẵn:
        {clipped_report}{truncation_note}

        NHIỆM VỤ (giữ đúng thứ tự):
        1) Đánh giá nhanh chất lượng dữ liệu nguồn và điểm nào đáng tin cậy nhất để kết luận.
        2) Liệt kê đúng 3 Pros quan trọng nhất cho cổ phiếu, dựa trên kết quả kinh doanh, bảng cân đối, dòng tiền hoặc triển vọng.
        3) Liệt kê đúng 3 Cons/rủi ro quan trọng nhất cho cổ phiếu.
        4) Đánh giá chất lượng lợi nhuận, sức khỏe tài chính và động lực tăng trưởng/suy giảm của doanh nghiệp.
        5) Kết luận tác động kinh tế đối với mã cổ phiếu trong ngắn hạn và trung hạn.

        OUTPUT:
        - Pros: 3 gạch đầu dòng, nêu rõ luận điểm.
        - Cons: 3 gạch đầu dòng, nêu rõ luận điểm.
        - Chất lượng lợi nhuận: Mạnh / Trung bình / Yếu.
        - Sức khỏe tài chính: Mạnh / Trung bình / Yếu.
        - Tác động ngắn hạn: tích cực / trung tính / tiêu cực.
        - Tác động trung hạn: tích cực / trung tính / tiêu cực.
        - Kết luận cuối cùng phải có dòng: `Dự đoán ảnh hưởng: [+/- X%]`.
        """

        try:
            result = await call_llm(
                system_prompt,
                user_prompt,
                model=models.t2_financial_model,
            )
        except LLMError as exc:
            return _ensure_impact_line(
                f"Không thể hoàn tất phân tích tài chính cho {ticker.upper()} {quarter_label}/{year}: {exc}"
            )

        if "<thinking>" not in result:
            print("[Financial Agent] ⚠️ Missing <thinking> tag in response", file=sys.stderr)
        return _ensure_impact_line(result)
