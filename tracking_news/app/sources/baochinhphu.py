import json
import re
from html import unescape
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup

from app.config import STORE_CONTENT_HTML, STORE_RAW_HTML
from app.extract.normalize import normalize_text
from app.sources import ArticleCandidate, SectionSeed

DEFAULT_BAOCHINHPHU_SECTIONS: tuple[SectionSeed, ...] = (
    SectionSeed(
        "chinh-sach-moi",
        "https://baochinhphu.vn/chinh-sach-va-cuoc-song/chinh-sach-moi.htm",
    ),
)

_ARTICLE_URL_RE = re.compile(r"^https?://baochinhphu\.vn/(?!chu-de/).+-\d+\.htm$")


def _meta_content(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    if node is None:
        return None
    content = node.get("content")
    if isinstance(content, str) and content.strip():
        return unescape(content.strip())
    return None


def _iter_json_ld_items(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.get_text(strip=True)
        if not raw:
            continue
        raw = raw.replace("\r", "").replace("\n", "")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            items.append(payload)
        elif isinstance(payload, list):
            items.extend(item for item in payload if isinstance(item, dict))
    return items


def _json_ld_news_value(soup: BeautifulSoup, key: str) -> str | None:
    for item in _iter_json_ld_items(soup):
        if item.get("@type") != "NewsArticle":
            continue
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return unescape(value.strip())
    return None


def _json_ld_breadcrumb_name(soup: BeautifulSoup) -> str | None:
    for item in _iter_json_ld_items(soup):
        if item.get("@type") != "BreadcrumbList":
            continue
        elements = item.get("itemListElement")
        if not isinstance(elements, list):
            continue
        for element in reversed(elements):
            if not isinstance(element, dict):
                continue
            nested_item = element.get("item")
            if not isinstance(nested_item, dict):
                continue
            name = nested_item.get("name")
            if isinstance(name, str) and name.strip() and name.strip().lower() != "trang chủ":
                return unescape(name.strip())
    return None


class BaoChinhPhuAdapter:
    source_name = "baochinhphu"
    sections = DEFAULT_BAOCHINHPHU_SECTIONS

    def list_page_published_at_values(self, html: str, *, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        values: list[str] = []
        seen: set[str] = set()
        for node in soup.select("span.box-category-time[title], span.box-stream-time[title]"):
            value = node.get("title")
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            values.append(normalized)
        return values

    def discover_next_page_url(
        self, html: str, *, section: SectionSeed, current_url: str
    ) -> str | None:
        current_match = re.search(r"/timelinelist/(\d+)/(\d+)\.htm$", current_url)
        if current_match:
            zone_id = current_match.group(1)
            next_page = int(current_match.group(2)) + 1
            return f"https://baochinhphu.vn/timelinelist/{zone_id}/{next_page}.htm"

        node = BeautifulSoup(html, "lxml").select_one("#hdZoneId")
        zone_id = node.get("value") if node is not None else None
        if not isinstance(zone_id, str) or not zone_id.strip():
            return None
        return f"https://baochinhphu.vn/timelinelist/{zone_id.strip()}/2.htm"

    def parse_list_page(self, html: str, *, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        seen: set[str] = set()

        for link in soup.select(
            ".box-category-middle a.box-category-link-title[href], .box-stream a.box-stream-link-title[href], .timeline_list a.box-stream-link-title[href]"
        ):
            href = urljoin(base_url, str(link.get("href", "")).replace("\\", "/")).split("#", 1)[0]
            if not _ARTICLE_URL_RE.match(href):
                continue
            if href in seen:
                continue
            seen.add(href)
            urls.append(href)

        return urls

    def parse_article(self, url: str, html: str) -> ArticleCandidate:
        soup = BeautifulSoup(html, "lxml")
        content_node = soup.select_one(
            '.detail-content.afcbc-body[data-role="content"]'
        ) or soup.select_one(".detail-content.afcbc-body")

        title = normalize_text(
            self._text_or_none(soup.select_one("h1.detail-title"))
            or _meta_content(soup, 'meta[property="og:title"]')
            or ""
        )
        category = normalize_text(_json_ld_breadcrumb_name(soup) or "") or None
        published_at = _meta_content(
            soup, 'meta[property="article:published_time"]'
        ) or _json_ld_news_value(soup, "datePublished")

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
            for node in content_node.select("p, h2, h3, li"):
                self._append_text(parts, seen, node.get_text(" ", strip=True))

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

    @staticmethod
    def _append_text(parts: list[str], seen: set[str], value: str) -> None:
        text = normalize_text(value)
        if not text or text in seen:
            return
        seen.add(text)
        parts.append(text)
