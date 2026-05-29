"""Async financial RAG report generation with sector-specific questionnaires."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from config import paths
from vnstock.agents.financial_agent import (
    CachedFinancialReport,
    get_cached_financial_report,
    normalize_financial_quarter,
)
from vnstock.agents.sector_questions import SectorQuestionSet, get_question_set_for_ticker
from vnstock.libs.rag_engine.retrieval import query_func


ANALYSIS_REPORTS_DIR = paths.analysis_reports_dir
RAG_STORAGE_DIR = paths.rag_storage_dir
QUERY_MODE = "hybrid"
MAX_CONCURRENT_RAG_QUERIES = 9
MAX_CITATIONS_PER_QUESTION = 2
MAX_CITATION_CHARS = 8192
QUESTION_TIMEOUT_SECONDS = 2400


class FinancialAnalysisError(RuntimeError):
    """Raised when the financial RAG pipeline cannot produce a report."""


@dataclass(frozen=True)
class Citation:
    label: str
    excerpt: str


@dataclass(frozen=True)
class QuestionResult:
    number: int
    question: str
    answer: str
    citations: tuple[Citation, ...]
    error: str | None = None


@dataclass(frozen=True)
class ReportArtifact:
    ticker: str
    year: str
    quarter: str
    sector_name: str
    path: Path
    content: str
    reused_cache: bool


def log_progress(msg: str) -> None:
    print(msg, file=sys.stderr)


def _report_path(ticker: str, year: str, quarter: str) -> Path:
    return ANALYSIS_REPORTS_DIR / f"{ticker.upper()}_{year}_{quarter}.md"


def _rag_working_dir(ticker: str, year: str, quarter: str) -> Path:
    return RAG_STORAGE_DIR / ticker.upper() / year / quarter


def _read_cached_report(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise FinancialAnalysisError(f"Không đọc được báo cáo cached tại {path}: {exc}") from exc
    return content or None


def _normalize_excerpt(text: str) -> str:
    excerpt = " ".join(text.split())
    if len(excerpt) > MAX_CITATION_CHARS:
        return f"{excerpt[: MAX_CITATION_CHARS - 1].rstrip()}…"
    return excerpt


def _pick_citation_excerpt(context: str) -> str:
    cleaned_lines = [line.strip(" |-*\t") for line in context.splitlines() if line.strip()]
    preferred_lines = [line for line in cleaned_lines if any(char.isdigit() for char in line)]
    candidates = preferred_lines or cleaned_lines
    if not candidates:
        return ""
    return _normalize_excerpt(candidates[0])


def _extract_citations(contexts: Sequence[str]) -> tuple[Citation, ...]:
    citations: list[Citation] = []
    seen_excerpts: set[str] = set()

    for index, context in enumerate(contexts, start=1):
        excerpt = _pick_citation_excerpt(context)
        if not excerpt or excerpt in seen_excerpts:
            continue
        seen_excerpts.add(excerpt)
        citations.append(Citation(label=f"Nguồn {index}", excerpt=excerpt))
        if len(citations) >= MAX_CITATIONS_PER_QUESTION:
            break

    return tuple(citations)


def _clean_answer(answer: str) -> str:
    cleaned = " ".join(str(answer).split())
    return cleaned or "Chưa truy xuất được câu trả lời từ hệ thống RAG."


def _format_citations(citations: Sequence[Citation]) -> str:
    if not citations:
        return "- Không tìm thấy trích đoạn OCR đủ rõ để đính kèm nguồn."
    return "\n".join(f"- **{citation.label}:** {citation.excerpt}" for citation in citations)


def _format_question_result(result: QuestionResult) -> str:
    body_lines = [
        f"### Câu {result.number}. {result.question}",
        f"**Nhận định:** {result.answer}",
        "**Trích dẫn OCR:**",
        _format_citations(result.citations),
    ]
    if result.error:
        body_lines.append(f"**Ghi chú lỗi:** {result.error}")
    return "\n".join(body_lines)


def _build_report_markdown(
    *,
    ticker: str,
    year: str,
    quarter: str,
    question_set: SectorQuestionSet,
    results: Sequence[QuestionResult],
) -> str:
    sections: list[str] = [
        f"# BÁO CÁO PHÂN TÍCH TÀI CHÍNH CHUYÊN SÂU: {ticker} - {quarter}/{year}",
        "",
        f"- **Ngành áp dụng:** {question_set.display_name}",
        f"- **Nguồn dữ liệu:** Financial RAG tại `{_rag_working_dir(ticker, year, quarter)}`",
        (
            "- **Phương pháp:** Bộ 25 câu hỏi chuyên ngành  "
            "`asyncio.Semaphore(5)` để giới hạn tối đa 5 truy vấn RAG đồng thời."
        ),
        "- **Nguyên tắc trích dẫn:** Chỉ sử dụng dữ liệu lấy từ OCR context của báo cáo tài chính.",
        "",
    ]

    result_index = 0
    for section in question_set.sections:
        sections.append(f"## {section.title}")
        sections.append("")
        for _ in section.questions:
            sections.append(_format_question_result(results[result_index]))
            sections.append("")
            result_index += 1

    return "\n".join(sections).strip() + "\n"


async def _query_single_question(
    *,
    semaphore: asyncio.Semaphore,
    ticker: str,
    year: str,
    quarter: str,
    question: str,
    number: int,
) -> QuestionResult:
    log_progress(f"[FinancialAnalysis] Bắt đầu câu {number}: {question}")
    try:
        async with semaphore:
            contexts, answer = await asyncio.wait_for(
                query_func(
                    None,
                    question=question,
                    mode=QUERY_MODE,
                    ticker=ticker,
                    year=year,
                    quarter=quarter,
                ),
                timeout=QUESTION_TIMEOUT_SECONDS,
            )
    except Exception as exc:
        error_message = f"RAG query thất bại ({type(exc).__name__}): {exc}"
        log_progress(f"[FinancialAnalysis] Câu {number} lỗi: {error_message}")
        return QuestionResult(
            number=number,
            question=question,
            answer="Không truy xuất được câu trả lời do lỗi hệ thống RAG.",
            citations=(),
            error=error_message,
        )

    if isinstance(contexts, str):
        normalized_contexts = (contexts,) if contexts.strip() else ()
    else:
        normalized_contexts = tuple(
            context for context in contexts if isinstance(context, str) and context.strip()
        )
    log_progress(
        f"[FinancialAnalysis] Xong câu {number}: lấy được {len(normalized_contexts)} context chunk(s)"
    )
    return QuestionResult(
        number=number,
        question=question,
        answer=_clean_answer(answer),
        citations=_extract_citations(normalized_contexts),
    )


class FinancialAnalysisAgent:
    """Generate sector-aware markdown financial reports from the OCR-backed RAG store."""

    def __init__(self, ticker: str, year: str | int, quarter: str | int) -> None:
        self.ticker = str(ticker).strip().upper()
        self.year = str(year).strip()
        self.quarter = normalize_financial_quarter(quarter)
        self.question_set = get_question_set_for_ticker(self.ticker)
        self.report_path = _report_path(self.ticker, self.year, self.quarter)
        self.rag_dir = _rag_working_dir(self.ticker, self.year, self.quarter)

    async def generate(self) -> ReportArtifact:
        cached_content = _read_cached_report(self.report_path)
        if cached_content:
            # Keep the on-disk cache authoritative so repeated analysis does not spend RAG time.
            log_progress(f"Báo cáo này đã được phân tích và lưu rồi: {self.report_path}")
            return ReportArtifact(
                ticker=self.ticker,
                year=self.year,
                quarter=self.quarter,
                sector_name=self.question_set.display_name,
                path=self.report_path,
                content=cached_content,
                reused_cache=True,
            )

        if not self.rag_dir.exists():
            raise FinancialAnalysisError(
                f"Chưa có dữ liệu RAG cho {self.ticker} {self.quarter}/{self.year} tại {self.rag_dir}"
            )

        ANALYSIS_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        log_progress(
            "[FinancialAnalysis] Bắt đầu tạo báo cáo "
            f"{self.ticker} {self.quarter}/{self.year} với "
            f"{len(self.question_set.all_questions)} câu hỏi"
        )
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_RAG_QUERIES)
        tasks = [
            _query_single_question(
                semaphore=semaphore,
                ticker=self.ticker,
                year=self.year,
                quarter=self.quarter,
                question=question,
                number=index,
            )
            for index, question in enumerate(self.question_set.all_questions, start=1)
        ]
        results = await asyncio.gather(*tasks)

        if not results:
            raise FinancialAnalysisError(
                f"Không có kết quả phân tích nào được tạo cho {self.ticker} {self.quarter}/{self.year}"
            )

        report_content = _build_report_markdown(
            ticker=self.ticker,
            year=self.year,
            quarter=self.quarter,
            question_set=self.question_set,
            results=results,
        )
        try:
            self.report_path.write_text(report_content, encoding="utf-8")
        except OSError as exc:
            raise FinancialAnalysisError(
                f"Không ghi được báo cáo phân tích ra đĩa tại {self.report_path}: {exc}"
            ) from exc

        error_count = sum(1 for result in results if result.error)
        log_progress(
            f"[FinancialAnalysis] Đã lưu báo cáo tại {self.report_path} "
            f"(lỗi: {error_count}/{len(results)} câu)"
        )

        return ReportArtifact(
            ticker=self.ticker,
            year=self.year,
            quarter=self.quarter,
            sector_name=self.question_set.display_name,
            path=self.report_path,
            content=report_content,
            reused_cache=False,
        )


async def generate_financial_report(
    ticker: str,
    year: str | int,
    quarter: str | int,
) -> ReportArtifact:
    agent = FinancialAnalysisAgent(ticker=ticker, year=year, quarter=quarter)
    return await agent.generate()


class DynamicFinancialAgent:
    def __init__(
        self,
        ticker: str,
        year: str,
        quarter: str,
        output_dir: str = "analysis_reports",
    ) -> None:
        del output_dir
        self.ticker = ticker.upper()
        self.year = str(year)
        self.quarter = normalize_financial_quarter(quarter)
        self.output_dir = ANALYSIS_REPORTS_DIR

    def _get_report_path(self) -> str:
        return str(_report_path(self.ticker, self.year, self.quarter))

    def _get_legacy_report_path(self) -> str:
        filename = f"{self.ticker}_{self.year}_{self.quarter}_Analysis.md"
        return str(self.output_dir / filename)

    def _resolve_report(self, ref_date: str | None) -> CachedFinancialReport | None:
        if ref_date:
            return get_cached_financial_report(self.ticker, ref_date=ref_date)
        return get_cached_financial_report(
            self.ticker,
            year=self.year,
            quarter=self.quarter,
        )

    async def analyze(self, *, ref_date: str | None = None) -> str:
        if ref_date:
            report = self._resolve_report(ref_date)
            if report is None:
                return (
                    f"❌ LỖI: Không tìm thấy báo cáo tài chính cached cho {self.ticker} "
                    f"với mốc {ref_date}."
                )
            log_progress(f"[FinancialAgent] cache hit: {report.path}")
            return report.content

        artifact = await generate_financial_report(self.ticker, self.year, self.quarter)
        log_progress(f"[FinancialAgent] report ready: {artifact.path}")
        return artifact.content


__all__ = [
    "DynamicFinancialAgent",
    "FinancialAnalysisAgent",
    "FinancialAnalysisError",
    "ReportArtifact",
    "generate_financial_report",
]
