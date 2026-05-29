import json
import re
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup

from app.config import STORE_CONTENT_HTML, STORE_RAW_HTML
from app.extract.normalize import normalize_text
from app.sources import ArticleCandidate, SectionSeed

DEFAULT_VIETNAMNET_SECTIONS: tuple[SectionSeed, ...] = (
    SectionSeed("kinh-doanh", "https://vietnamnet.vn/kinh-doanh"),
)

_ARTICLE_URL_RE = re.compile(r"^https?://vietnamnet\.vn/(?!.*-tag\d+\.html$).+-\d+\.html$")


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


def _json_ld_value(soup: BeautifulSoup, key: str) -> str | None:
    for item in _iter_json_ld_items(soup):
        if item.get("@type") != "NewsArticle":
            continue
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
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
            if isinstance(nested_item, dict):
                name = nested_item.get("name")
                if isinstance(name, str) and name.strip() and name.strip().lower() != "trang chủ":
                    return name.strip()
            name = element.get("name")
            if isinstance(name, str) and name.strip() and name.strip().lower() != "trang chủ":
                return name.strip()
    return None


class VietnamNetAdapter:
    source_name = "vietnamnet"
    sections = DEFAULT_VIETNAMNET_SECTIONS

    def parse_list_page(self, html: str, *, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        seen: set[str] = set()

        for link in soup.select("a[href]"):
            href = str(link.get("href", "")).replace("\\", "/")
            absolute_url = urljoin(base_url, href).split("#", 1)[0]
            if not _ARTICLE_URL_RE.match(absolute_url):
                continue
            if absolute_url in seen:
                continue
            seen.add(absolute_url)
            urls.append(absolute_url)

        return urls

    def discover_next_page_url(
        self, html: str, *, section: SectionSeed, current_url: str
    ) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        link = soup.select_one('link[rel="next"]') or soup.select_one("li.pagination-next a[href]")
        href = link.get("href") if link is not None else None
        if not isinstance(href, str) or not href.strip() or href.startswith("javascript:"):
            return None
        next_url = urljoin(current_url, href).split("#", 1)[0]
        return next_url if next_url != current_url else None

    def parse_article(self, url: str, html: str) -> ArticleCandidate:
        soup = BeautifulSoup(html, "lxml")
        content_node = soup.select_one(".maincontent.main-content")

        title = normalize_text(
            self._text_or_none(soup.select_one("h1.content-detail-title"))
            or _meta_content(soup, 'meta[property="og:title"]')
            or ""
        )
        category = normalize_text(_json_ld_breadcrumb_name(soup) or "") or None
        published_at = _json_ld_value(soup, "datePublished") or self._text_or_none(
            soup.select_one(".publish-date")
        )

        content_text = self._extract_content_text(html, content_node, soup)
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

    def _extract_content_text(self, html: str, content_node, soup: BeautifulSoup) -> str:
        parts: list[str] = []
        seen: set[str] = set()

        summary = self._text_or_none(soup.select_one("h2.content-detail-sapo"))
        if summary:
            self._append_text(parts, seen, summary)

        if content_node is not None:
            for node in content_node.select("p, h2, h3"):
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
