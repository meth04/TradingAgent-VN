import json
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import trafilatura
from bs4 import BeautifulSoup

from app.extract.normalize import normalize_text
from app.sources import ArticleCandidate, SectionSeed, SkipArticleError


@dataclass(frozen=True, slots=True)
class CafeFSectionConfig:
    name: str
    url: str
    zone_id: str
    label: str


CAFEF_SECTION_CONFIGS: tuple[CafeFSectionConfig, ...] = (
    CafeFSectionConfig(
        "thi-truong-chung-khoan",
        "https://cafef.vn/thi-truong-chung-khoan.chn",
        "18831",
        "Thị trường chứng khoán",
    ),
    CafeFSectionConfig(
        "bat-dong-san",
        "https://cafef.vn/bat-dong-san.chn",
        "18835",
        "Bất động sản",
    ),
    CafeFSectionConfig(
        "doanh-nghiep",
        "https://cafef.vn/doanh-nghiep.chn",
        "18836",
        "Doanh nghiệp",
    ),
    CafeFSectionConfig(
        "tai-chinh-ngan-hang",
        "https://cafef.vn/tai-chinh-ngan-hang.chn",
        "18834",
        "Tài chính - Ngân hàng",
    ),
    CafeFSectionConfig(
        "tai-chinh-quoc-te",
        "https://cafef.vn/tai-chinh-quoc-te.chn",
        "18832",
        "Tài chính quốc tế",
    ),
    CafeFSectionConfig(
        "vi-mo-dau-tu",
        "https://cafef.vn/vi-mo-dau-tu.chn",
        "18833",
        "Vĩ mô - Đầu tư",
    ),
    CafeFSectionConfig(
        "thi-truong",
        "https://cafef.vn/thi-truong.chn",
        "18839",
        "Thị trường",
    ),
    CafeFSectionConfig(
        "song",
        "https://cafef.vn/song.chn",
        "188114",
        "Sống",
    ),
)
CAFEF_SECTION_BY_NAME: dict[str, CafeFSectionConfig] = {
    item.name: item for item in CAFEF_SECTION_CONFIGS
}
DEFAULT_CAFEF_SECTIONS: tuple[SectionSeed, ...] = tuple(
    SectionSeed(item.name, item.url) for item in CAFEF_SECTION_CONFIGS
)

_ARTICLE_URL_RE = re.compile(
    r"^https?://cafef\.vn/(?!du-lieu/|video/|thi-truong-chung-khoan\.chn$|bat-dong-san\.chn$|doanh-nghiep\.chn$|tai-chinh-ngan-hang\.chn$|tai-chinh-quoc-te\.chn$|vi-mo-dau-tu\.chn$|thi-truong\.chn$|song\.chn$).+-\d+\.chn$"
)
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
    "kcn",
    "khu kinh tế",
    "m&a",
    "mua bán sáp nhập",
    "trái phiếu",
    "tín dụng",
    "ngân hàng",
    "doanh nghiệp",
    "chủ đầu tư",
    "niêm yết",
    "cổ phiếu",
    "huy động vốn",
    "vốn",
    "dự án",
    "cao tốc",
    "sân bay",
    "hạ tầng",
    "giải phóng mặt bằng",
    "mục đích sử dụng đất",
    "thu tiền sử dụng đất",
)
_DENY_BDS_TERMS = (
    "lifestyle",
    "sống",
    "nhà đẹp",
    "kiến trúc",
    "nội thất",
    "ngoại thất",
    "căn bếp",
    "phòng ngủ",
    "phòng khách",
    "homestay",
    "villa",
    "resort",
    "ngôi nhà",
    "mẫu nhà",
    "thiết kế",
    "không gian sống",
)


def cafef_timelinelist_url(zone_id: str, page_number: int) -> str:
    return f"https://cafef.vn/timelinelist/{zone_id}/{page_number}.chn"


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


class CafeFAdapter:
    source_name = "cafef"
    sections = DEFAULT_CAFEF_SECTIONS
    section_configs = CAFEF_SECTION_CONFIGS

    def get_section_config(self, section: SectionSeed) -> CafeFSectionConfig:
        return CAFEF_SECTION_BY_NAME[section.name]

    def timelinelist_url(self, *, section: SectionSeed, page_number: int) -> str:
        return cafef_timelinelist_url(self.get_section_config(section).zone_id, page_number)

    def list_page_published_at_values(self, html: str, *, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        values: list[str] = []
        seen: set[str] = set()
        for node in soup.select("p.time[data-time], span.time[title]"):
            raw = node.get("data-time") or node.get("title")
            if not isinstance(raw, str):
                continue
            normalized = raw.strip()
            if normalized.startswith(("206/", "207/", "208/", "209/")):
                normalized = normalized[1:]
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            values.append(normalized)
        return values

    def discover_next_page_url(
        self, html: str, *, section: SectionSeed, current_url: str
    ) -> str | None:
        current_match = re.search(r"/timelinelist/(\d+)/(\d+)\.chn$", current_url)
        if current_match:
            zone_id = current_match.group(1)
            next_page = int(current_match.group(2)) + 1
            return cafef_timelinelist_url(zone_id, next_page)

        section_config = CAFEF_SECTION_BY_NAME.get(section.name)
        if section_config is not None:
            return cafef_timelinelist_url(section_config.zone_id, 2)

        zone_id = self._extract_zone_id(html)
        if zone_id is None:
            return None
        return cafef_timelinelist_url(zone_id, 2)

    def parse_list_page(self, html: str, *, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        seen: set[str] = set()

        for link in soup.select(
            ".listchungkhoannew .tlitem h3 a[href], .listchungkhoannew .tlitem-flex .avatar[href], .tlitem h3 a[href], .tlitem-flex .avatar[href]"
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
            self._text_or_none(soup.select_one('h1[data-role="title"], h1.title'))
            or _meta_content(soup, 'meta[property="og:title"]')
            or ""
        )
        category = (
            normalize_text(
                self._text_or_none(
                    soup.select_one('a[data-role="cate-name"], .category-page__name.cat')
                )
                or _json_ld_news_value(soup, "articleSection")
                or ""
            )
            or None
        )
        published_at = self._extract_published_at(soup)
        content_text = self._extract_content_text(html, content_node)

        self._ensure_relevant(url=url, category=category, title=title, content_text=content_text)

        store_content_html = os.getenv("STORE_CONTENT_HTML", "1") == "1"
        store_raw_html = os.getenv("STORE_RAW_HTML", "0") == "1"
        content_html = (
            str(content_node) if content_node is not None and store_content_html else None
        )
        raw_html = html if store_raw_html else None

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
        self, *, url: str, category: str | None, title: str, content_text: str
    ) -> None:
        slug = urlparse(url).path.lower()
        if "/bat-dong-san" not in slug and category != "Bất động sản":
            return

        haystack = normalize_text(f"{category or ''}\n{title}\n{content_text}").lower()
        if any(term in haystack for term in _DENY_BDS_TERMS):
            raise SkipArticleError("cafef real-estate article out of scope")
        if not any(term in haystack for term in _ALLOWED_BDS_TERMS):
            raise SkipArticleError("cafef real-estate article lacks financial relevance")

    @staticmethod
    def _extract_zone_id(html: str) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        node = soup.select_one("#hdZoneId")
        zone_id = node.get("value") if node is not None else None
        if isinstance(zone_id, str) and zone_id.strip():
            return zone_id.strip()

        match = re.search(r"(?:zoneid|zone)(\d{4,})", html, re.IGNORECASE)
        if match:
            return match.group(1)

        return None

    @staticmethod
    def _extract_published_at(soup: BeautifulSoup) -> str | None:
        return (
            _meta_content(soup, 'meta[property="article:published_time"]')
            or _json_ld_news_value(soup, "datePublished")
            or CafeFAdapter._text_or_none(soup.select_one('span.pdate[data-role="publishdate"]'))
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
                if node.find_parent(id="listNewsInContent") is not None:
                    continue
                text = normalize_text(node.get_text(" ", strip=True))
                if not text or text in seen:
                    continue
                if text == "TIN MỚI":
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
