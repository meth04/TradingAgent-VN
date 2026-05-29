import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import NamedTuple

import httpx

from app.config import (
    ARTICLE_FETCH_WORKERS,
    CAFEF_REBUILD_OLD_PAGE_STREAK,
    CAFEF_REBUILD_PAGE_CAP,
    INGEST_DATE_FROM,
    INGEST_DATE_TO,
    MAX_CONSECUTIVE_OUT_OF_WINDOW_LIST_PAGES,
    MAX_CONSECUTIVE_STALE_PAGES,
    MAX_EXTRA_PAGES_PER_SECTION,
    MAX_PAGES_PER_SECTION,
    MIN_UNIQUE_URLS_TO_EXTEND,
)
from app.db.articles_repo import ArticleRecord, insert_article
from app.db.crawl_state_repo import upsert_crawl_state
from app.db.ingest_runs_repo import IngestRunCounts
from app.dedup.hashers import compute_content_sha256, compute_simhash64, compute_simhash_bucket
from app.extract.datetime_utils import (
    MissingPublishedAtError,
    normalize_published_at,
    published_date_from_iso,
)
from app.extract.http_client import fetch_html
from app.extract.normalize import normalize_text
from app.fomo.scorer import score_fomo
from app.sources import (
    ArticleCandidate,
    SectionDiscoveryStats,
    SectionSeed,
    SkipArticleError,
    SourceAdapter,
)
from app.sources.cafef import CafeFAdapter
from app.tickers.vn30 import extract_vn30_tickers

logger = logging.getLogger(__name__)


class DiscoveredArticle(NamedTuple):
    url: str
    seed_section: str
    topic_label: str | None


TOPIC_LABEL_BY_SECTION: dict[str, str] = {
    "tai-chinh-ngan-hang": "banking",
    "kinh-doanh": "business",
    "kinh-te": "business",
    "tai-chinh-chung-khoan": "business",
    "doanh-nghiep": "business",
    "chinh-sach-moi": "macro_policy",
    "tai-chinh-quoc-te": "macro_policy",
    "vi-mo-dau-tu": "macro_policy",
    "bat-dong-san": "real_estate",
    "thi-truong-chung-khoan": "stocks",
    "thi-truong": "business",
    "song": "business",
}


@dataclass(slots=True)
class PipelineResult:
    counts: IngestRunCounts
    fetched_urls: int
    processed_urls: int
    failed_urls: list[str]
    section_stats: list[SectionDiscoveryStats] = field(default_factory=list)


class PreparedArticle(NamedTuple):
    discovered: DiscoveredArticle
    candidate: ArticleCandidate | None
    exception: Exception | None = None


class RunOncePipeline:
    def __init__(
        self,
        adapter: SourceAdapter,
        *,
        client: httpx.Client | None = None,
        article_fetch_workers: int | None = None,
        article_rate_limit_seconds: float | None = None,
    ):
        self.adapter = adapter
        self.client = client
        self.article_fetch_workers = max(1, article_fetch_workers or ARTICLE_FETCH_WORKERS)
        self.article_rate_limit_seconds = article_rate_limit_seconds

    def run(self, con: sqlite3.Connection) -> PipelineResult:
        discovered_articles, section_stats = self._discover_article_urls(con)
        counts = IngestRunCounts()
        failed_urls: list[str] = []
        processed = 0
        stats_by_section = {item.section_name: item for item in section_stats}

        for prepared in self._prepare_articles(discovered_articles):
            discovered = prepared.discovered
            url = discovered.url
            section_stats_item = stats_by_section[discovered.seed_section]
            try:
                if prepared.exception is not None:
                    raise prepared.exception
                candidate = prepared.candidate
                if candidate is None:
                    continue

                processed += 1
                section_stats_item.processed_urls += 1

                published_at = normalize_published_at(candidate.published_at)
                published_date = published_date_from_iso(published_at)
                if published_date < INGEST_DATE_FROM or published_date > INGEST_DATE_TO:
                    counts.dropped_out_of_window_count += 1
                    section_stats_item.dropped_out_of_window_count += 1
                    continue

                if (
                    section_stats_item.latest_published_at is None
                    or published_at > section_stats_item.latest_published_at
                ):
                    section_stats_item.latest_published_at = published_at

                content_text = normalize_text(candidate.content_text)
                if not content_text:
                    logger.warning("dropping article without content_text: %s", url)
                    continue

                tickers = extract_vn30_tickers(f"{candidate.title}\n{content_text}")
                fomo_score, explain_json = score_fomo(candidate.title, content_text, tickers)
                content_sha256 = compute_content_sha256(content_text)
                simhash64 = compute_simhash64(content_text)
                simhash_bucket = compute_simhash_bucket(simhash64)

                record = ArticleRecord(
                    title=candidate.title,
                    url=candidate.url,
                    source=candidate.source,
                    category=candidate.category,
                    seed_section=discovered.seed_section,
                    topic_label=discovered.topic_label,
                    published_at=published_at,
                    published_date=published_date,
                    content_text=content_text,
                    content_html=candidate.content_html,
                    raw_html=candidate.raw_html,
                    tickers=tickers,
                    fomo_score=fomo_score,
                    fomo_explain_json=explain_json,
                    content_sha256=content_sha256,
                    simhash64=simhash64,
                    simhash_bucket=simhash_bucket,
                )
                insert_result = insert_article(con, record)
                if insert_result.inserted:
                    counts.inserted_count += 1
                    section_stats_item.inserted_count += 1
                elif insert_result.reason in {"exact_sha256", "near_simhash", "duplicate_url"}:
                    counts.dedup_dropped_count += 1
                    section_stats_item.dedup_dropped_count += 1
            except MissingPublishedAtError:
                counts.dropped_no_date_count += 1
                section_stats_item.dropped_no_date_count += 1
                logger.warning("dropping article without published_at: %s", url)
            except SkipArticleError:
                counts.dropped_irrelevant_count += 1
                section_stats_item.dropped_irrelevant_count += 1
                logger.warning("dropping irrelevant article: %s", url)
            except Exception:
                failed_urls.append(url)
                section_stats_item.failed_count += 1
                logger.exception(
                    "failed to ingest article: source=%s url=%s", self.adapter.source_name, url
                )

        return PipelineResult(
            counts=counts,
            fetched_urls=len(discovered_articles),
            processed_urls=processed,
            failed_urls=failed_urls,
            section_stats=section_stats,
        )

    def _prepare_articles(
        self, discovered_articles: list[DiscoveredArticle]
    ) -> list[PreparedArticle]:
        if not discovered_articles:
            return []
        if self.article_fetch_workers <= 1:
            return [self._fetch_and_parse_article(discovered) for discovered in discovered_articles]

        with ThreadPoolExecutor(max_workers=self.article_fetch_workers) as executor:
            return list(executor.map(self._fetch_and_parse_article, discovered_articles))

    def _fetch_and_parse_article(self, discovered: DiscoveredArticle) -> PreparedArticle:
        try:
            html = fetch_html(
                discovered.url,
                client=self.client,
                rate_limit_seconds=self.article_rate_limit_seconds,
            )
            candidate = self.adapter.parse_article(discovered.url, html)
            return PreparedArticle(discovered=discovered, candidate=candidate)
        except Exception as exc:
            return PreparedArticle(discovered=discovered, candidate=None, exception=exc)

    def _discover_article_urls(
        self, con: sqlite3.Connection
    ) -> tuple[list[DiscoveredArticle], list[SectionDiscoveryStats]]:
        discovered_articles: list[DiscoveredArticle] = []
        seen: set[str] = set()
        all_section_stats: list[SectionDiscoveryStats] = []

        for section in self.adapter.sections:
            self._mark_section_running(con, section)
            stats = SectionDiscoveryStats(section_name=section.name, section_url=section.url)
            all_section_stats.append(stats)
            section_seen_pages: set[str] = set()
            next_url: str | None = section.url
            stale_pages = 0
            out_of_window_pages = 0
            topic_label = TOPIC_LABEL_BY_SECTION.get(section.name)
            page_limit = MAX_PAGES_PER_SECTION

            try:
                while next_url and stats.pages_scanned < page_limit:
                    if next_url in section_seen_pages:
                        break
                    section_seen_pages.add(next_url)

                    html = fetch_html(next_url, client=self.client)
                    stats.pages_scanned += 1
                    section_urls = self.adapter.parse_list_page(html, base_url=next_url)
                    stats.discovered_urls += len(section_urls)

                    new_unique = 0
                    for url in section_urls:
                        if url in seen:
                            continue
                        seen.add(url)
                        discovered_articles.append(
                            DiscoveredArticle(
                                url=url,
                                seed_section=section.name,
                                topic_label=topic_label,
                            )
                        )
                        new_unique += 1
                    stats.unique_urls += new_unique

                    stale_pages = stale_pages + 1 if new_unique == 0 else 0
                    if self._list_page_is_out_of_window(html, next_url):
                        out_of_window_pages += 1
                    else:
                        out_of_window_pages = 0

                    candidate_next = self._discover_next_page_url(
                        html, section=section, current_url=next_url
                    )
                    if candidate_next is None or candidate_next in section_seen_pages:
                        break
                    if stale_pages >= MAX_CONSECUTIVE_STALE_PAGES:
                        break
                    if out_of_window_pages >= MAX_CONSECUTIVE_OUT_OF_WINDOW_LIST_PAGES:
                        break
                    if (
                        stats.pages_scanned >= MAX_PAGES_PER_SECTION
                        and new_unique >= MIN_UNIQUE_URLS_TO_EXTEND
                    ):
                        page_limit = MAX_PAGES_PER_SECTION + MAX_EXTRA_PAGES_PER_SECTION
                    next_url = candidate_next
            except Exception as exc:
                upsert_crawl_state(
                    con,
                    source=self.adapter.source_name,
                    section=section.name,
                    status="error",
                    error=str(exc),
                    last_published_at=stats.latest_published_at,
                )
                raise

            upsert_crawl_state(
                con,
                source=self.adapter.source_name,
                section=section.name,
                status="ok",
                error=None,
                last_published_at=stats.latest_published_at,
            )
        return discovered_articles, all_section_stats

    def _discover_next_page_url(
        self,
        html: str,
        *,
        section: SectionSeed,
        current_url: str,
    ) -> str | None:
        discover_next = getattr(self.adapter, "discover_next_page_url", None)
        if callable(discover_next):
            return discover_next(html, section=section, current_url=current_url)
        return None

    def _list_page_is_out_of_window(self, html: str, current_url: str) -> bool:
        extractor = getattr(self.adapter, "list_page_published_at_values", None)
        if not callable(extractor):
            return False
        values = extractor(html, base_url=current_url)
        if not values:
            return False

        oldest_published_date: str | None = None
        for value in values:
            try:
                published_date = published_date_from_iso(normalize_published_at(value))
            except MissingPublishedAtError:
                continue
            if oldest_published_date is None or published_date < oldest_published_date:
                oldest_published_date = published_date

        return oldest_published_date is not None and oldest_published_date < INGEST_DATE_FROM

    def _mark_section_running(self, con: sqlite3.Connection, section: SectionSeed) -> None:
        upsert_crawl_state(
            con,
            source=self.adapter.source_name,
            section=section.name,
            status="running",
            error=None,
        )


class CafeFRebuildPipeline:
    def __init__(
        self,
        adapter: CafeFAdapter | None = None,
        *,
        client: httpx.Client | None = None,
        page_cap: int | None = None,
        old_page_streak: int | None = None,
        article_rate_limit_seconds: float | None = None,
    ):
        self.adapter = adapter or CafeFAdapter()
        self.client = client
        self.page_cap = max(1, page_cap or CAFEF_REBUILD_PAGE_CAP)
        self.old_page_streak = max(1, old_page_streak or CAFEF_REBUILD_OLD_PAGE_STREAK)
        self.article_rate_limit_seconds = article_rate_limit_seconds

    def run(self, con: sqlite3.Connection) -> PipelineResult:
        counts = IngestRunCounts()
        failed_urls: list[str] = []
        section_stats: list[SectionDiscoveryStats] = []
        seen_urls: set[str] = set()
        processed = 0

        for section in self.adapter.sections:
            stats = SectionDiscoveryStats(section_name=section.name, section_url=section.url)
            section_stats.append(stats)
            section_seen_pages: set[str] = set()
            topic_label = TOPIC_LABEL_BY_SECTION.get(section.name)
            old_page_streak = 0

            self._mark_section_running(con, section)

            try:
                for page_number in range(1, self.page_cap + 1):
                    page_url = self._page_url(section, page_number)
                    if page_url in section_seen_pages:
                        break
                    section_seen_pages.add(page_url)

                    list_html = fetch_html(page_url, client=self.client)
                    stats.pages_scanned += 1
                    page_urls = self.adapter.parse_list_page(list_html, base_url=page_url)
                    stats.discovered_urls += len(page_urls)
                    if not page_urls:
                        break

                    page_valid_published_dates = 0
                    page_old_published_dates = 0
                    page_had_new_unique_urls = False

                    for url in page_urls:
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        stats.unique_urls += 1
                        page_had_new_unique_urls = True

                        try:
                            article_html = fetch_html(
                                url,
                                client=self.client,
                                rate_limit_seconds=self.article_rate_limit_seconds,
                            )
                            candidate = self.adapter.parse_article(url, article_html)
                            processed += 1
                            stats.processed_urls += 1

                            published_at = normalize_published_at(candidate.published_at)
                            published_date = published_date_from_iso(published_at)
                            page_valid_published_dates += 1

                            if published_date < INGEST_DATE_FROM:
                                page_old_published_dates += 1
                                counts.dropped_out_of_window_count += 1
                                stats.dropped_out_of_window_count += 1
                                continue
                            if published_date > INGEST_DATE_TO:
                                counts.dropped_out_of_window_count += 1
                                stats.dropped_out_of_window_count += 1
                                continue

                            if (
                                stats.latest_published_at is None
                                or published_at > stats.latest_published_at
                            ):
                                stats.latest_published_at = published_at

                            content_text = normalize_text(candidate.content_text)
                            if not content_text:
                                logger.warning("dropping article without content_text: %s", url)
                                continue

                            tickers = extract_vn30_tickers(f"{candidate.title}\n{content_text}")
                            fomo_score, explain_json = score_fomo(
                                candidate.title, content_text, tickers
                            )
                            content_sha256 = compute_content_sha256(content_text)
                            simhash64 = compute_simhash64(content_text)
                            simhash_bucket = compute_simhash_bucket(simhash64)

                            record = ArticleRecord(
                                title=candidate.title,
                                url=candidate.url,
                                source=candidate.source,
                                category=candidate.category,
                                seed_section=section.name,
                                topic_label=topic_label,
                                published_at=published_at,
                                published_date=published_date,
                                content_text=content_text,
                                content_html=candidate.content_html,
                                raw_html=candidate.raw_html,
                                tickers=tickers,
                                fomo_score=fomo_score,
                                fomo_explain_json=explain_json,
                                content_sha256=content_sha256,
                                simhash64=simhash64,
                                simhash_bucket=simhash_bucket,
                            )
                            insert_result = insert_article(con, record)
                            if insert_result.inserted:
                                counts.inserted_count += 1
                                stats.inserted_count += 1
                            elif insert_result.reason in {
                                "exact_sha256",
                                "near_simhash",
                                "duplicate_url",
                            }:
                                counts.dedup_dropped_count += 1
                                stats.dedup_dropped_count += 1
                        except MissingPublishedAtError:
                            counts.dropped_no_date_count += 1
                            stats.dropped_no_date_count += 1
                            logger.warning("dropping article without published_at: %s", url)
                        except SkipArticleError:
                            counts.dropped_irrelevant_count += 1
                            stats.dropped_irrelevant_count += 1
                            logger.warning("dropping irrelevant article: %s", url)
                        except Exception:
                            failed_urls.append(url)
                            stats.failed_count += 1
                            logger.exception("failed to ingest CafeF article: url=%s", url)

                    if not page_had_new_unique_urls:
                        break

                    if (
                        page_valid_published_dates > 0
                        and page_old_published_dates == page_valid_published_dates
                    ):
                        old_page_streak += 1
                    else:
                        old_page_streak = 0

                    if old_page_streak >= self.old_page_streak:
                        break
            except Exception as exc:
                upsert_crawl_state(
                    con,
                    source=self.adapter.source_name,
                    section=section.name,
                    status="error",
                    error=str(exc),
                    last_published_at=stats.latest_published_at,
                )
                raise

            upsert_crawl_state(
                con,
                source=self.adapter.source_name,
                section=section.name,
                status="ok",
                error=None,
                last_published_at=stats.latest_published_at,
            )

        return PipelineResult(
            counts=counts,
            fetched_urls=len(seen_urls),
            processed_urls=processed,
            failed_urls=failed_urls,
            section_stats=section_stats,
        )

    def _page_url(self, section: SectionSeed, page_number: int) -> str:
        if page_number == 1:
            return section.url
        return self.adapter.timelinelist_url(section=section, page_number=page_number)

    def _mark_section_running(self, con: sqlite3.Connection, section: SectionSeed) -> None:
        upsert_crawl_state(
            con,
            source=self.adapter.source_name,
            section=section.name,
            status="running",
            error=None,
        )
