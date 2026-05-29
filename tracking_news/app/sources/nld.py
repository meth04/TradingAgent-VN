import json
import re
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup

from app.config import STORE_CONTENT_HTML, STORE_RAW_HTML
from app.extract.normalize import normalize_text
from app.sources import ArticleCandidate, SectionSeed

DEFAULT_NLD_SECTIONS: tuple[SectionSeed, ...] = (
    SectionSeed("kinh-te", "https://nld.com.vn/kinh-te.htm"),
)

_ARTICLE_URL_RE = re.compile(r"^https?://nld\.com\.vn/.+-\d+\.htm$")


def _meta_content(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    if node is None:
        return None
    content = node.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


def _iter_json_ld_items(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.get_text(strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            items.append(payload)
        elif isinstance(payload, list):
            items.extend(item for item in payload if isinstance(item, dict))
    return items


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
            if isinstance(nested_item, dict):
                name = nested_item.get("name")
                if isinstance(name, str) and name.strip() and name.strip().lower() != "trang chủ":
                    return name.strip()
    return None


class NguoiLaoDongAdapter:
    source_name = "nld"
    sections = DEFAULT_NLD_SECTIONS

    def discover_next_page_url(
        self, html: str, *, section: SectionSeed, current_url: str
    ) -> str | None:
        current_match = re.search(r"/timelinelist/(\d+)/(\d+)\.htm$", current_url)
        if current_match:
            zone_id = current_match.group(1)
            next_page = int(current_match.group(2)) + 1
            return f"https://nld.com.vn/timelinelist/{zone_id}/{next_page}.htm"

        zone_id = self._attr_or_none(BeautifulSoup(html, "lxml").select_one("#hdZoneId"), "value")
        if not zone_id:
            return None
        return f"https://nld.com.vn/timelinelist/{zone_id}/2.htm"

    def parse_list_page(self, html: str, *, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        seen: set[str] = set()

        for link in soup.select("a[href]"):
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
        category = (
            normalize_text(
                _meta_content(soup, 'meta[property="article:section"]')
                or _json_ld_breadcrumb_name(soup)
                or ""
            )
            or None
        )
        published_at = _meta_content(
            soup, 'meta[property="article:published_time"]'
        ) or self._attr_or_none(soup.select_one("time[datetime]"), "datetime")

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

    @staticmethod
    def _attr_or_none(node, attr: str) -> str | None:
        if node is None:
            return None
        value = node.get(attr)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _extract_content_text(self, html: str, content_node) -> str:
        parts: list[str] = []
        seen: set[str] = set()

        if content_node is not None:
            for node in content_node.select("p, h2, h3"):
                if node.find_parent(attrs={"data-role": "newsrelation"}) is not None:
                    continue
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
