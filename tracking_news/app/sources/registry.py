from dataclasses import dataclass

from app.sources import SectionSeed, SourceAdapter
from app.sources.baochinhphu import BaoChinhPhuAdapter
from app.sources.baodautu import BaoDauTuAdapter
from app.sources.cafef import CafeFAdapter
from app.sources.dantri import DanTriAdapter
from app.sources.nld import NguoiLaoDongAdapter
from app.sources.tuoitre import TuoiTreAdapter
from app.sources.vietnamnet import VietnamNetAdapter
from app.sources.vnexpress import VnExpressAdapter


@dataclass(frozen=True, slots=True)
class SeedSource:
    source_name: str
    seed: SectionSeed
    enabled: bool
    status: str
    note: str | None = None


ENABLED_SOURCES: tuple[str, ...] = (
    "vnexpress",
    "dantri",
    "tuoitre",
    "vietnamnet",
    "baodautu",
    "nld",
    "baochinhphu",
    "cafef",
)

SUPPORTED_SOURCE_ADAPTERS: tuple[SourceAdapter, ...] = (
    VnExpressAdapter(),
    DanTriAdapter(),
    TuoiTreAdapter(),
    VietnamNetAdapter(),
    BaoDauTuAdapter(),
    NguoiLaoDongAdapter(),
    BaoChinhPhuAdapter(),
    CafeFAdapter(),
)

SEED_SOURCES: tuple[SeedSource, ...] = (
    SeedSource(
        "vnexpress",
        SectionSeed("kinh-doanh", "https://vnexpress.net/kinh-doanh"),
        True,
        "supported",
    ),
    SeedSource(
        "vnexpress",
        SectionSeed("bat-dong-san", "https://vnexpress.net/bat-dong-san"),
        True,
        "supported",
    ),
    SeedSource(
        "dantri",
        SectionSeed("kinh-doanh", "https://dantri.com.vn/kinh-doanh.htm"),
        True,
        "supported",
    ),
    SeedSource(
        "tuoitre", SectionSeed("kinh-doanh", "https://tuoitre.vn/kinh-doanh.htm"), True, "supported"
    ),
    SeedSource(
        "vietnamnet",
        SectionSeed("kinh-doanh", "https://vietnamnet.vn/kinh-doanh"),
        True,
        "supported",
    ),
    SeedSource(
        "cafef",
        SectionSeed("thi-truong-chung-khoan", "https://cafef.vn/thi-truong-chung-khoan.chn"),
        True,
        "supported",
        "HTML adapter enabled with article-page published_at extraction.",
    ),
    SeedSource(
        "cafef",
        SectionSeed("bat-dong-san", "https://cafef.vn/bat-dong-san.chn"),
        True,
        "supported",
        "HTML adapter enabled with real-estate relevance filtering.",
    ),
    SeedSource(
        "cafef",
        SectionSeed("doanh-nghiep", "https://cafef.vn/doanh-nghiep.chn"),
        True,
        "supported",
        "HTML adapter enabled with article-page published_at extraction.",
    ),
    SeedSource(
        "cafef",
        SectionSeed("tai-chinh-ngan-hang", "https://cafef.vn/tai-chinh-ngan-hang.chn"),
        True,
        "supported",
        "HTML adapter enabled with article-page published_at extraction.",
    ),
    SeedSource(
        "cafef",
        SectionSeed("tai-chinh-quoc-te", "https://cafef.vn/tai-chinh-quoc-te.chn"),
        True,
        "supported",
        "HTML adapter enabled with article-page published_at extraction.",
    ),
    SeedSource(
        "cafef",
        SectionSeed("vi-mo-dau-tu", "https://cafef.vn/vi-mo-dau-tu.chn"),
        True,
        "supported",
        "HTML adapter enabled with article-page published_at extraction.",
    ),
    SeedSource(
        "cafef",
        SectionSeed("thi-truong", "https://cafef.vn/thi-truong.chn"),
        True,
        "supported",
        "HTML adapter enabled with article-page published_at extraction.",
    ),
    SeedSource(
        "cafef",
        SectionSeed("song", "https://cafef.vn/song.chn"),
        True,
        "supported",
        "HTML adapter enabled with article-page published_at extraction.",
    ),
    SeedSource(
        "vneconomy",
        SectionSeed("thi-truong-chung-khoan", "https://vneconomy.vn/thi-truong-chung-khoan.htm"),
        False,
        "pending",
        "Deferred until selector stability is evaluated.",
    ),
    SeedSource(
        "vietstock",
        SectionSeed("chung-khoan", "https://vietstock.vn/chung-khoan.htm"),
        False,
        "pending",
        "Deferred until selector stability is evaluated.",
    ),
    SeedSource(
        "baodautu",
        SectionSeed("tai-chinh-chung-khoan", "https://baodautu.vn/tai-chinh-chung-khoan-d6/"),
        True,
        "supported",
    ),
    SeedSource(
        "vtv",
        SectionSeed("tai-chinh", "https://vtv.vn/kinh-te/tai-chinh.htm"),
        False,
        "pending",
        "Deferred; JS-heavy risk remains for this rollout.",
    ),
    SeedSource("nld", SectionSeed("kinh-te", "https://nld.com.vn/kinh-te.htm"), True, "supported"),
    SeedSource(
        "laodong",
        SectionSeed("kinh-doanh", "https://laodong.vn/kinh-doanh"),
        False,
        "skipped",
        "List page returned near-empty HTML during probe.",
    ),
    SeedSource(
        "baochinhphu",
        SectionSeed(
            "chinh-sach-moi",
            "https://baochinhphu.vn/chinh-sach-va-cuoc-song/chinh-sach-moi.htm",
        ),
        True,
        "supported",
    ),
    SeedSource(
        "mof",
        SectionSeed("tin-tuc-tai-chinh", "https://mof.gov.vn/tin-tuc-tai-chinh"),
        False,
        "skipped",
        "List page probe did not expose stable article links for HTML-only rollout.",
    ),
)


def get_seed_sources() -> list[SeedSource]:
    return list(SEED_SOURCES)


def get_source_adapters(enabled_sources: str | None = None) -> list[SourceAdapter]:
    adapters_by_name = {adapter.source_name: adapter for adapter in SUPPORTED_SOURCE_ADAPTERS}
    default_names = [name for name in ENABLED_SOURCES if name in adapters_by_name]

    if enabled_sources is None or not enabled_sources.strip():
        return [adapters_by_name[name] for name in default_names]

    selected_names = [name.strip().lower() for name in enabled_sources.split(",") if name.strip()]
    unknown_names = [name for name in selected_names if name not in adapters_by_name]
    if unknown_names:
        known_names = ", ".join(sorted(adapters_by_name))
        unknown_list = ", ".join(sorted(unknown_names))
        raise ValueError(f"unknown source(s): {unknown_list}. available sources: {known_names}")

    return [adapters_by_name[name] for name in selected_names]
