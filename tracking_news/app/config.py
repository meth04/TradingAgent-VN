import os
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NEWS_DB_PATH = PROJECT_ROOT / "data" / "news.db"


def _env_iso_date(name: str, default: str) -> str:
    return date.fromisoformat(os.getenv(name, default)).isoformat()


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0") == "1"


NEWS_DB_PATH = os.getenv("NEWS_DB_PATH", str(DEFAULT_NEWS_DB_PATH))

STORE_CONTENT_HTML = _env_bool("STORE_CONTENT_HTML", True)
STORE_RAW_HTML = _env_bool("STORE_RAW_HTML", False)

USE_PLAYWRIGHT = _env_bool("USE_PLAYWRIGHT", False)

INGEST_DATE_FROM = _env_iso_date("INGEST_DATE_FROM", "2026-01-01")
INGEST_DATE_TO = _env_iso_date("INGEST_DATE_TO", date.today().isoformat())
MAX_PAGES_PER_SECTION = _env_int("MAX_PAGES_PER_SECTION", 32)
MAX_EXTRA_PAGES_PER_SECTION = _env_int("MAX_EXTRA_PAGES_PER_SECTION", 32)
MIN_UNIQUE_URLS_TO_EXTEND = _env_int("MIN_UNIQUE_URLS_TO_EXTEND", 8)
MAX_CONSECUTIVE_STALE_PAGES = _env_int("MAX_CONSECUTIVE_STALE_PAGES", 3)
MAX_CONSECUTIVE_OUT_OF_WINDOW_LIST_PAGES = _env_int("MAX_CONSECUTIVE_OUT_OF_WINDOW_LIST_PAGES", 2)
ARTICLE_FETCH_WORKERS = max(1, _env_int("ARTICLE_FETCH_WORKERS", 1))
CAFEF_ONLY_ARTICLE_FETCH_WORKERS = max(1, _env_int("CAFEF_ONLY_ARTICLE_FETCH_WORKERS", 4))
CAFEF_ONLY_ARTICLE_RATE_LIMIT_SECONDS = float(
    os.getenv("CAFEF_ONLY_ARTICLE_RATE_LIMIT_SECONDS", "0.0")
)
CAFEF_DEEP_BACKFILL_MODE = _env_bool("CAFEF_DEEP_BACKFILL_MODE", False)
CAFEF_DEEP_BACKFILL_PAGE_CAP = max(1, _env_int("CAFEF_DEEP_BACKFILL_PAGE_CAP", 1200))
CAFEF_REBUILD_PAGE_CAP = max(1, _env_int("CAFEF_REBUILD_PAGE_CAP", 1200))
CAFEF_REBUILD_OLD_PAGE_STREAK = max(1, _env_int("CAFEF_REBUILD_OLD_PAGE_STREAK", 1))

CRAWL_USER_AGENT = os.getenv(
    "CRAWL_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
)
CRAWL_TIMEOUT_SECONDS = float(os.getenv("CRAWL_TIMEOUT_SECONDS", "20"))
CRAWL_RATE_LIMIT_SECONDS = float(os.getenv("CRAWL_RATE_LIMIT_SECONDS", "1.0"))
