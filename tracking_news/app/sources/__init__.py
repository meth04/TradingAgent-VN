from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SectionSeed:
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class ArticleCandidate:
    title: str
    url: str
    source: str
    category: str | None
    published_at: str | None
    content_text: str
    content_html: str | None = None
    raw_html: str | None = None


@dataclass(slots=True)
class SectionDiscoveryStats:
    section_name: str
    section_url: str
    pages_scanned: int = 0
    discovered_urls: int = 0
    unique_urls: int = 0
    processed_urls: int = 0
    inserted_count: int = 0
    dropped_no_date_count: int = 0
    dropped_irrelevant_count: int = 0
    dropped_out_of_window_count: int = 0
    dedup_dropped_count: int = 0
    failed_count: int = 0
    latest_published_at: str | None = None


class SkipArticleError(ValueError):
    pass


class SourceAdapter(Protocol):
    source_name: str
    sections: Sequence[SectionSeed]

    def parse_list_page(self, html: str, *, base_url: str) -> list[str]: ...

    def parse_article(self, url: str, html: str) -> ArticleCandidate: ...


class PaginatedSourceAdapter(SourceAdapter, Protocol):
    def discover_next_page_url(
        self,
        html: str,
        *,
        section: SectionSeed,
        current_url: str,
    ) -> str | None: ...


class ListPageDateAwareAdapter(SourceAdapter, Protocol):
    def list_page_published_at_values(self, html: str, *, base_url: str) -> list[str]: ...
