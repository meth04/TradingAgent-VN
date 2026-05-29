import logging
import os

from app.config import (
    ARTICLE_FETCH_WORKERS,
    CAFEF_ONLY_ARTICLE_FETCH_WORKERS,
    CAFEF_ONLY_ARTICLE_RATE_LIMIT_SECONDS,
)
from app.db.conn import connect
from app.db.crawl_state_repo import upsert_crawl_state
from app.db.ingest_runs_repo import (
    IngestRunCounts,
    finish_ingest_run,
    insert_ingest_section_runs,
    start_ingest_run,
)
from app.db.init_db import init_db
from app.extract.http_client import build_client
from app.ingest.pipeline import PipelineResult, RunOncePipeline
from app.sources.registry import get_source_adapters


def _merge_counts(total: IngestRunCounts, current: IngestRunCounts) -> None:
    total.inserted_count += current.inserted_count
    total.dropped_no_date_count += current.dropped_no_date_count
    total.dropped_irrelevant_count += current.dropped_irrelevant_count
    total.dropped_out_of_window_count += current.dropped_out_of_window_count
    total.dedup_dropped_count += current.dedup_dropped_count


def _print_source_summary(source_name: str, result: PipelineResult) -> None:
    pages_scanned = sum(item.pages_scanned for item in result.section_stats)
    discovered_urls = sum(item.discovered_urls for item in result.section_stats)
    unique_urls = sum(item.unique_urls for item in result.section_stats)
    print(
        f"[{source_name}]",
        f"pages_scanned={pages_scanned}",
        f"discovered_raw={discovered_urls}",
        f"discovered_unique={unique_urls}",
        f"processed={result.processed_urls}",
        f"inserted={result.counts.inserted_count}",
        f"latest_published_at={max((item.latest_published_at for item in result.section_stats if item.latest_published_at), default=None)}",
        f"dropped_no_date={result.counts.dropped_no_date_count}",
        f"dropped_irrelevant={result.counts.dropped_irrelevant_count}",
        f"dropped_out_of_window={result.counts.dropped_out_of_window_count}",
        f"dedup_dropped={result.counts.dedup_dropped_count}",
        f"failed={len(result.failed_urls)}",
    )
    for item in result.section_stats:
        print(
            f"[{source_name}:{item.section_name}]",
            f"pages_scanned={item.pages_scanned}",
            f"discovered_raw={item.discovered_urls}",
            f"discovered_unique={item.unique_urls}",
            f"processed={item.processed_urls}",
            f"inserted={item.inserted_count}",
            f"dropped_no_date={item.dropped_no_date_count}",
            f"dropped_irrelevant={item.dropped_irrelevant_count}",
            f"dropped_out_of_window={item.dropped_out_of_window_count}",
            f"dedup_dropped={item.dedup_dropped_count}",
            f"failed={item.failed_count}",
            f"latest_published_at={item.latest_published_at}",
        )
    if result.failed_urls:
        print(f"[{source_name}] failed_urls:")
        for url in result.failed_urls[:20]:
            print(f"- {url}")


def _cafef_only_mode_enabled() -> bool:
    return os.getenv("CAFEF_ONLY_MODE", "0") == "1"


def _resolve_enabled_sources() -> str | None:
    enabled_sources = os.getenv("ENABLED_SOURCES")
    if enabled_sources and enabled_sources.strip():
        return enabled_sources
    if _cafef_only_mode_enabled():
        return "cafef"
    return None


def _resolve_article_fetch_workers(source_name: str) -> int:
    if _cafef_only_mode_enabled() and source_name == "cafef":
        return CAFEF_ONLY_ARTICLE_FETCH_WORKERS
    return ARTICLE_FETCH_WORKERS


def _resolve_article_rate_limit_seconds(source_name: str) -> float | None:
    if _cafef_only_mode_enabled() and source_name == "cafef":
        return CAFEF_ONLY_ARTICLE_RATE_LIMIT_SECONDS
    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    init_db()

    adapters = get_source_adapters(_resolve_enabled_sources())

    with connect() as con, build_client() as client:
        run_id = start_ingest_run(con, mode="manual")
        total_counts = IngestRunCounts()
        total_fetched_urls = 0
        total_processed_urls = 0
        total_pages_scanned = 0
        total_discovered_raw = 0
        total_failed_urls: list[str] = []

        try:
            for adapter in adapters:
                try:
                    result = RunOncePipeline(
                        adapter,
                        client=client,
                        article_fetch_workers=_resolve_article_fetch_workers(adapter.source_name),
                        article_rate_limit_seconds=_resolve_article_rate_limit_seconds(
                            adapter.source_name
                        ),
                    ).run(con)
                except Exception as exc:
                    logging.exception("source failed and will be skipped: %s", adapter.source_name)
                    for section in adapter.sections:
                        upsert_crawl_state(
                            con,
                            source=adapter.source_name,
                            section=section.name,
                            status="error",
                            error=str(exc),
                        )
                    print(f"[{adapter.source_name}] skipped error={exc}")
                    continue

                insert_ingest_section_runs(con, run_id, adapter.source_name, result.section_stats)

                _merge_counts(total_counts, result.counts)
                total_fetched_urls += result.fetched_urls
                total_processed_urls += result.processed_urls
                total_pages_scanned += sum(item.pages_scanned for item in result.section_stats)
                total_discovered_raw += sum(item.discovered_urls for item in result.section_stats)
                total_failed_urls.extend(result.failed_urls)
                _print_source_summary(adapter.source_name, result)
        except Exception as exc:
            finish_ingest_run(con, run_id, total_counts, error=str(exc))
            raise

        finish_ingest_run(con, run_id, total_counts)

    print(
        "run_once completed:",
        f"sources={len(adapters)}",
        f"pages_scanned={total_pages_scanned}",
        f"discovered_raw={total_discovered_raw}",
        f"discovered_unique={total_fetched_urls}",
        f"processed={total_processed_urls}",
        f"inserted={total_counts.inserted_count}",
        f"dropped_no_date={total_counts.dropped_no_date_count}",
        f"dropped_irrelevant={total_counts.dropped_irrelevant_count}",
        f"dropped_out_of_window={total_counts.dropped_out_of_window_count}",
        f"dedup_dropped={total_counts.dedup_dropped_count}",
        f"failed={len(total_failed_urls)}",
    )


if __name__ == "__main__":
    main()
