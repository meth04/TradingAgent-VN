import re
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup

from app.config import STORE_CONTENT_HTML, STORE_RAW_HTML
from app.extract.normalize import normalize_text
from app.sources import ArticleCandidate, SectionSeed

DEFAULT_TUOITRE_SECTIONS: tuple[SectionSeed, ...] = (
    SectionSeed("kinh-doanh", "https://tuoitre.vn/kinh-doanh.htm"),
)

_ARTICLE_URL_RE = re.compile(
    r"^https?://tuoitre\.vn/(?!kinh-doanh(?:/|\.htm$)|tin-moi-nhat|tin-xem-nhieu|video|can-biet|danh-cho-ban|tac-gia/).+-\d{12,17}\.htm$"
)


def _meta_content(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    if node is None:
        return None
    content = node.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


class TuoiTreAdapter:
    source_name = "tuoitre"
    sections = DEFAULT_TUOITRE_SECTIONS

    def discover_next_page_url(
        self, html: str, *, section: SectionSeed, current_url: str
    ) -> str | None:
        current_match = re.search(r"/timeline/(\d+)/trang-(\d+)\.htm$", current_url)
        if current_match:
            zone_id = current_match.group(1)
            next_page = int(current_match.group(2)) + 1
            return f"https://tuoitre.vn/timeline/{zone_id}/trang-{next_page}.htm"

        node = BeautifulSoup(html, "lxml").select_one("#hdZoneId")
        zone_id = node.get("value") if node is not None else None
        if not isinstance(zone_id, str) or not zone_id.strip():
            return None
        return f"https://tuoitre.vn/timeline/{zone_id.strip()}/trang-1.htm"

    def parse_list_page(self, html: str, *, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        seen: set[str] = set()

        for link in soup.select(
            "#load-list-news a[href], .timeline_list a[href], .box-category a.box-category-link-title[href], .box-sub-item a[href]"
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
        category = (
            normalize_text(self._text_or_none(soup.select_one(".detail-cate a")) or "") or None
        )
        published_at = _meta_content(
            soup, 'meta[property="article:published_time"]'
        ) or _meta_content(soup, 'meta[name="pubdate"]')
        if published_at is None:
            published_at = self._text_or_none(
                soup.select_one('.detail-time [data-role="publishdate"]')
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

        summary = self._text_or_none(soup.select_one('h2.detail-sapo[data-role="sapo"]'))
        if summary:
            self._append_text(parts, seen, summary)

        if content_node is not None:
            for node in content_node.select("p, h2, h3"):
                if node.find_parent(attrs={"type": "RelatedOneNews"}) is not None:
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
