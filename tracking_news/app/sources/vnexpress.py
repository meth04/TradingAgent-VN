import json
import re
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup

from app.config import STORE_CONTENT_HTML, STORE_RAW_HTML
from app.extract.normalize import normalize_text
from app.sources import ArticleCandidate, SectionSeed, SkipArticleError

DEFAULT_VNEXPRESS_SECTIONS: tuple[SectionSeed, ...] = (
    SectionSeed("kinh-doanh", "https://vnexpress.net/kinh-doanh"),
    SectionSeed("bat-dong-san", "https://vnexpress.net/bat-dong-san"),
)

_ARTICLE_URL_RE = re.compile(
    r"^https?://vnexpress\.net/(?!topic/|video/|podcast/|anh/|interactive/).+-\d+\.html$"
)
_ALLOWED_GENERAL_SECTIONS = {
    "kinh doanh",
    "chứng khoán",
    "doanh nghiệp",
    "ngân hàng",
    "vĩ mô",
    "quốc tế",
    "phân tích",
    "thị trường",
    "hàng hóa",
    "hạ tầng",
    "năng lượng",
    "bảo hiểm",
    "thuế",
    "đầu tư",
    "công nghiệp",
    "xuất nhập khẩu",
    "thương mại điện tử",
}
_DENIED_SECTIONS = {
    "nội thất",
    "ngoại thất",
    "kinh nghiệm",
    "tư vấn",
    "không gian sống",
    "nhà đẹp",
}
_ALLOWED_BDS_TERMS = (
    "bất động sản",
    "đất",
    "đất đai",
    "đấu giá",
    "đấu thầu",
    "quy hoạch",
    "pháp lý",
    "pháp lí",
    "tiền sử dụng đất",
    "khu công nghiệp",
    "khu kinh tế",
    "hạ tầng",
    "cao tốc",
    "sân bay",
    "dự án",
    "đô thị",
    "trái phiếu",
    "tín dụng",
    "m&a",
    "sáp nhập",
    "niêm yết",
    "cổ phiếu",
    "doanh nghiệp",
    "chủ đầu tư",
    "vốn",
    "fdi",
    "ldg",
    "nvl",
    "pdr",
    "khd",
    "nlg",
    "kdh",
    "vhm",
    "dxg",
)
_DENIED_BDS_TERMS = (
    "nội thất",
    "ngoại thất",
    "kinh nghiệm",
    "tư vấn",
    "không gian sống",
    "nhà đẹp",
    "lifestyle",
    "căn bếp",
    "phòng khách",
    "phòng ngủ",
    "mẫu nhà",
    "thiết kế",
    "resort",
    "homestay",
    "villa",
    "ngôi nhà",
)


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


def _json_ld_news_value(soup: BeautifulSoup, key: str) -> str | None:
    for item in _iter_json_ld_items(soup):
        if item.get("@type") != "NewsArticle":
            continue
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class VnExpressAdapter:
    source_name = "vnexpress"
    sections = DEFAULT_VNEXPRESS_SECTIONS

    def list_page_published_at_values(self, html: str, *, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        values: list[str] = []
        seen: set[str] = set()
        for article in soup.select("article.item-news, article.article-item"):
            raw = article.get("data-publishtime")
            if not isinstance(raw, str) or not raw.strip() or not raw.strip().isdigit():
                continue
            normalized = raw.strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            values.append(normalized)
        return values

    def parse_list_page(self, html: str, *, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        seen: set[str] = set()
        is_bat_dong_san = base_url.rstrip("/").endswith("/bat-dong-san")

        for article in soup.select("article.item-news, article.article-item"):
            if (
                article.select_one("[data-publishtime]") is None
                and article.get("data-publishtime") is None
            ):
                continue
            link = article.select_one(
                "h3.title-news a[href], h2 a[href], h3 a[href], a.thumb[href]"
            )
            if link is None:
                continue
            href = urljoin(base_url, str(link.get("href", ""))).split("#", 1)[0]
            if not _ARTICLE_URL_RE.match(href):
                continue

            title = normalize_text(link.get_text(" ", strip=True))
            description = normalize_text(
                self._text_or_none(article.select_one("p.description, p.sapo, .description")) or ""
            )
            if is_bat_dong_san and not self._is_relevant_bat_dong_san_text(
                f"{title}\n{description}"
            ):
                continue
            if href in seen:
                continue
            seen.add(href)
            urls.append(href)

        return urls

    def discover_next_page_url(
        self, html: str, *, section: SectionSeed, current_url: str
    ) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        link = soup.select_one('link[rel="next"]') or soup.select_one(
            "#pagination a.next-page[href]"
        )
        href = self._attr_or_none(link, "href")
        if not href or href.startswith("javascript:"):
            return None
        next_url = urljoin(current_url, href).split("#", 1)[0]
        return next_url if next_url != current_url else None

    def parse_article(self, url: str, html: str) -> ArticleCandidate:
        soup = BeautifulSoup(html, "lxml")
        content_node = soup.select_one("article.fck_detail") or soup.select_one(
            "div.sidebar-1 article"
        )

        title = normalize_text(
            self._text_or_none(soup.select_one("h1.title-detail"))
            or _meta_content(soup, 'meta[property="og:title"]')
            or ""
        )
        sections = self._article_sections(soup)
        category = (
            normalize_text(_meta_content(soup, 'meta[itemprop="articleSection"]') or "") or None
        )
        if category is None:
            category = next(
                (section for section in reversed(sections) if section[:1].isupper()), None
            )
        if category is None and sections:
            category = sections[-1]
        published_at = self._extract_published_at(soup)
        content_text = self._extract_content_text(soup, html, content_node)

        self._ensure_relevant(url=url, sections=sections, title=title, content_text=content_text)

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

    def _ensure_relevant(
        self, *, url: str, sections: list[str], title: str, content_text: str
    ) -> None:
        lowered_sections = {section.lower() for section in sections}
        if lowered_sections & _DENIED_SECTIONS:
            raise SkipArticleError("vnexpress article category out of scope")

        if "bất động sản" in lowered_sections:
            if not self._is_relevant_bat_dong_san_text("\n".join([*sections, title, content_text])):
                raise SkipArticleError("vnexpress real-estate article out of scope")
            return

        if lowered_sections and lowered_sections & _ALLOWED_GENERAL_SECTIONS:
            return

        if not lowered_sections and "bất động sản" not in url:
            return

    def _article_sections(self, soup: BeautifulSoup) -> list[str]:
        section_values: list[str] = []
        for value in (
            _meta_content(soup, 'meta[itemprop="articleSection"]'),
            _meta_content(soup, 'meta[name="tt_list_folder_name"]'),
            _meta_content(soup, 'meta[name="its_subsection"]'),
        ):
            if not value:
                continue
            for piece in value.split(","):
                text = normalize_text(piece)
                if text and text not in section_values and text.lower() != "vnexpress":
                    section_values.append(text)

        for link in soup.select(".breadcrumb li a"):
            text = normalize_text(link.get_text(" ", strip=True))
            if text and text not in section_values:
                section_values.append(text)

        return section_values

    @staticmethod
    def _extract_published_at(soup: BeautifulSoup) -> str | None:
        return _meta_content(soup, 'meta[itemprop="datePublished"]') or _json_ld_news_value(
            soup, "datePublished"
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

    def _extract_content_text(self, soup: BeautifulSoup, html: str, content_node) -> str:
        paragraphs: list[str] = []
        seen: set[str] = set()

        for node in soup.select("p.description"):
            text = normalize_text(node.get_text(" ", strip=True))
            if text and text not in seen:
                seen.add(text)
                paragraphs.append(text)

        if content_node is not None:
            for node in content_node.select("p.Normal, p"):
                text = normalize_text(node.get_text(" ", strip=True))
                if not text or text in seen:
                    continue
                seen.add(text)
                paragraphs.append(text)

        if not paragraphs:
            fallback = trafilatura.extract(
                html,
                include_comments=False,
                include_links=False,
                include_images=False,
            )
            if fallback:
                return normalize_text(fallback)

        return normalize_text("\n".join(paragraphs))

    def _is_relevant_bat_dong_san_text(self, text: str) -> bool:
        haystack = normalize_text(text).lower()
        if any(term in haystack for term in _DENIED_BDS_TERMS):
            return False
        return any(term in haystack for term in _ALLOWED_BDS_TERMS)
