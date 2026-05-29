import re
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup

from app.config import STORE_CONTENT_HTML, STORE_RAW_HTML
from app.extract.normalize import normalize_text
from app.sources import ArticleCandidate, SectionSeed

DEFAULT_BAODAUTU_SECTIONS: tuple[SectionSeed, ...] = (
    SectionSeed("tai-chinh-chung-khoan", "https://baodautu.vn/tai-chinh-chung-khoan-d6/"),
)

_ARTICLE_URL_RE = re.compile(r"^https?://baodautu\.vn/.+-d\d+\.html$")


def _meta_content(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    if node is None:
        return None
    content = node.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


class BaoDauTuAdapter:
    source_name = "baodautu"
    sections = DEFAULT_BAODAUTU_SECTIONS

    def parse_list_page(self, html: str, *, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        seen: set[str] = set()

        containers = soup.select(
            ".news_focus a[href], .list_news_home a[href], .news_top_box a[href], .list_thumb_square a[href]"
        )
        for link in containers:
            href = urljoin(base_url, str(link.get("href", "")).replace("\\", "/")).split("#", 1)[0]
            if not _ARTICLE_URL_RE.match(href):
                continue
            if href in seen:
                continue
            seen.add(href)
            urls.append(href)

        return urls

    def discover_next_page_url(
        self, html: str, *, section: SectionSeed, current_url: str
    ) -> str | None:
        match = re.search(r"/p(\d+)$", current_url)
        next_index = int(match.group(1)) + 1 if match else 2
        expected_suffix = f"/p{next_index}"

        soup = BeautifulSoup(html, "lxml")
        for link in soup.select("nav.pagation a[href]"):
            href = str(link.get("href", "")).strip()
            if not href or href.startswith("javascript:"):
                continue
            next_url = urljoin(current_url, href).split("#", 1)[0]
            if next_url.endswith(expected_suffix):
                return next_url
        return None

    def parse_article(self, url: str, html: str) -> ArticleCandidate:
        soup = BeautifulSoup(html, "lxml")
        content_node = soup.select_one(".col630.ml-auto.mb40")

        title = normalize_text(_meta_content(soup, 'meta[property="og:title"]') or "")
        category = (
            normalize_text(
                self._text_or_none(soup.select_one(".col630.ml-auto.mb40 a[href*='-d6/']")) or ""
            )
            or None
        )
        published_at = self._text_or_none(soup.select_one(".col630.ml-auto.mb40 .post-time"))
        if published_at and published_at.startswith("-"):
            published_at = published_at[1:].strip()

        content_text = self._extract_content_text(html, content_node)
        content_html = (
            str(content_node) if content_node is not None and STORE_CONTENT_HTML else None
        )
        raw_html = html if STORE_RAW_HTML else None

        return ArticleCandidate(
            title=title,
            url=url,
            source=self.source_name,
            category=category,
            published_at=published_at,
            content_text=content_text,
            content_html=content_html,
            raw_html=raw_html,
        )

    @staticmethod
    def _text_or_none(node) -> str | None:
        if node is None:
            return None
        text = node.get_text(" ", strip=True)
        return text or None

    def _extract_content_text(self, html: str, content_node) -> str:
        parts: list[str] = []
        seen: set[str] = set()

        if content_node is not None:
            summary = self._text_or_none(content_node.select_one(".sapo_detail"))
            if summary:
                seen.add(summary)
                parts.append(summary)

            for node in content_node.select("p"):
                text = normalize_text(node.get_text(" ", strip=True))
                if not text or text in seen:
                    continue
                if text.startswith("TIN LIÊN QUAN") or text.startswith("Từ khóa"):
                    continue
                seen.add(text)
                parts.append(text)

        if not parts:
            fallback = trafilatura.extract(
                html,
                include_comments=False,
                include_links=False,
                include_images=False,
            )
            if fallback:
                return normalize_text(fallback)

        return normalize_text("\n".join(parts))
