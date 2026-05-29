"""Market data service.

Three responsibilities:
1. Read latest close prices from `data/vnstock.db` (read-only via DataRepository).
2. Sync today's prices via MarketCrawler — `sync_prices_today()`.
3. Lightweight CafeF crawl into `app/data/news_cache.db` — `crawl_news_lite()`.

Per CLAUDE.md we never write to `data/`. All runtime writes live under `app/data/`.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from bootstrap import APP_DATA_DIR

# ── Paths ────────────────────────────────────────────────────────────────────
PRICE_CACHE_PATH = APP_DATA_DIR / "price_cache" / "today.json"
PRICE_SYNC_FLAG_PATH = APP_DATA_DIR / "price_cache" / "sync_flag.json"
NEWS_CACHE_DB_PATH = APP_DATA_DIR / "news_cache.db"
NEWS_SYNC_FLAG_PATH = APP_DATA_DIR / "news_cache_flag.json"

PRICE_CACHE_TTL_SECONDS = 60 * 30  # 30 min
PRICE_SYNC_TTL_SECONDS = 60 * 60  # don't re-sync the same ticker within 1h
NEWS_CRAWL_TTL_SECONDS = 0  # re-crawl every analyze call (per user request)

# 5 CafeF sections we keep (slug → URL). Must match section .name in
# tracking_news/app/sources/cafef.py so DEFAULT_CAFEF_SECTIONS filter works.
KEEP_CAFEF_SECTIONS = (
    "thi-truong-chung-khoan",
    "bat-dong-san",
    "doanh-nghiep",
    "tai-chinh-quoc-te",
    "vi-mo-dau-tu",
)
CAFEF_PAGES_PER_ZONE = 2


# ── Price cache (lightweight memo) ───────────────────────────────────────────
def _load_price_cache() -> Dict[str, Any]:
    if not PRICE_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(PRICE_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_price_cache(cache: Dict[str, Any]) -> None:
    PRICE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        PRICE_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _load_sync_flag(path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_sync_flag(path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Public: read prices ──────────────────────────────────────────────────────
def get_latest_prices(tickers: List[str]) -> Dict[str, float]:
    """Return {ticker: price_in_VND}. Reads OHLCV from data/vnstock.db.

    DB stores prices in thousands VND so we multiply by 1000 on the way out.
    """

    if not tickers:
        return {}

    cache = _load_price_cache()
    now = time.time()
    out: Dict[str, float] = {}
    missing: List[str] = []
    for t in tickers:
        key = t.upper()
        entry = cache.get(key)
        if entry and (now - float(entry.get("ts", 0))) < PRICE_CACHE_TTL_SECONDS:
            out[key] = float(entry["price"])
        else:
            missing.append(key)

    if missing:
        try:
            from vnstock.database.repo import DataRepository

            repo = DataRepository()
            try:
                for t in missing:
                    try:
                        df = repo.get_price_history(t, days=1)
                    except Exception:
                        df = None
                    if df is None or df.empty:
                        out[t] = 0.0
                        continue
                    last_close = float(df.iloc[-1]["close"]) * 1000.0
                    out[t] = last_close
                    cache[t] = {"price": last_close, "ts": now}
            finally:
                try:
                    repo.close()
                except Exception:
                    pass
            _save_price_cache(cache)
        except Exception as exc:  # pragma: no cover
            print(f"[market_service] price lookup failed: {exc}")
            for t in missing:
                out.setdefault(t, 0.0)

    return out


async def get_latest_prices_async(tickers: List[str]) -> Dict[str, float]:
    return await asyncio.to_thread(get_latest_prices, tickers)


# ── Public: sync prices via MarketCrawler ────────────────────────────────────
def sync_prices_today(tickers: List[str], *, force: bool = False) -> Dict[str, Any]:
    """Trigger MarketCrawler.sync_tickers for the given tickers.

    Skips tickers that were synced within PRICE_SYNC_TTL_SECONDS unless force=True.
    Returns {"synced": [...], "skipped": [...], "error": str|None, "duration_s": float}.
    """

    tickers = [t.strip().upper() for t in tickers if t and t.strip()]
    if not tickers:
        return {"synced": [], "skipped": [], "error": None, "duration_s": 0.0}

    flag = _load_sync_flag(PRICE_SYNC_FLAG_PATH)
    now = time.time()
    to_sync: List[str] = []
    skipped: List[str] = []
    for t in tickers:
        last = float((flag.get(t) or {}).get("ts", 0))
        if not force and (now - last) < PRICE_SYNC_TTL_SECONDS:
            skipped.append(t)
        else:
            to_sync.append(t)

    if not to_sync:
        return {"synced": [], "skipped": skipped, "error": None, "duration_s": 0.0}

    error: Optional[str] = None
    t0 = time.time()
    try:
        from vnstock.database.models import init_db
        from vnstock.jobs.crawler import MarketCrawler

        init_db()
        crawler = MarketCrawler()
        try:
            crawler.sync_tickers(to_sync, include_benchmarks=False)
        finally:
            try:
                crawler.repo.close()
            except Exception:
                pass
        # Invalidate price memo cache for just-synced tickers so next read is fresh.
        cache = _load_price_cache()
        for t in to_sync:
            cache.pop(t, None)
            flag[t] = {"ts": now}
        _save_price_cache(cache)
        _save_sync_flag(PRICE_SYNC_FLAG_PATH, flag)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    return {
        "synced": to_sync,
        "skipped": skipped,
        "error": error,
        "duration_s": round(time.time() - t0, 2),
    }


async def sync_prices_today_async(
    tickers: List[str], *, force: bool = False
) -> Dict[str, Any]:
    return await asyncio.to_thread(sync_prices_today, tickers, force=force)


# ── News crawl via tracking_news pipeline ────────────────────────────────────
def _legacy_news_cache_schema(db_path) -> bool:
    """Return True if news_cache.db exists but uses the old lightweight schema
    (no `content_text` column). We delete it so tracking_news's init_db can
    rebuild with the full schema SearchToolkit expects.
    """
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(articles)").fetchall()}
        finally:
            conn.close()
    except Exception:
        return False
    return bool(cols) and "content_text" not in cols


NEWS_WINDOW_DAYS = 5  # crawl `today - (N-1)` ... `today` so news covers ~5 days


def _patch_tracking_news(today_iso: str) -> None:
    """Monkey-patch tracking_news modules:
    - Date window: last NEWS_WINDOW_DAYS (inclusive of today).
    - CafeF sections: only the 5 we want.
    - FOMO scoring: no-op (we don't use it as a signal).
    """
    # ROOT/tracking_news is on sys.path (bootstrap.py), so `app` resolves there.
    from app import config as tn_config
    from app.sources import SectionSeed
    from app.sources import cafef as tn_cafef
    from app.fomo import scorer as tn_fomo

    window_start = (date.fromisoformat(today_iso) - timedelta(days=NEWS_WINDOW_DAYS - 1)).isoformat()
    tn_config.INGEST_DATE_FROM = window_start
    tn_config.INGEST_DATE_TO = today_iso
    tn_config.MAX_PAGES_PER_SECTION = CAFEF_PAGES_PER_ZONE
    tn_config.MAX_EXTRA_PAGES_PER_SECTION = CAFEF_PAGES_PER_ZONE

    kept = tuple(
        c for c in tn_cafef.CAFEF_SECTION_CONFIGS if c.name in KEEP_CAFEF_SECTIONS
    )
    tn_cafef.CAFEF_SECTION_CONFIGS = kept
    tn_cafef.CAFEF_SECTION_BY_NAME = {c.name: c for c in kept}
    tn_cafef.DEFAULT_CAFEF_SECTIONS = tuple(
        SectionSeed(c.name, c.url) for c in kept
    )
    # CafeFAdapter.sections / .section_configs are class attributes evaluated at
    # class-definition time, and the adapter instance is created module-level in
    # registry.py — so the module-level rebinds above don't reach the live
    # instance. Patch the class attributes too.
    tn_cafef.CafeFAdapter.sections = tn_cafef.DEFAULT_CAFEF_SECTIONS
    tn_cafef.CafeFAdapter.section_configs = kept

    noop = lambda *a, **kw: (0.0, "{}")  # noqa: E731
    tn_fomo.score_fomo = noop
    # pipeline.py imports score_fomo by name → patch its bound reference too.
    try:
        from app.ingest import pipeline as tn_pipeline

        tn_pipeline.score_fomo = noop
    except Exception:
        pass


def crawl_news_lite(*, force: bool = False) -> Dict[str, Any]:
    """Crawl CafeF via the full tracking_news pipeline into app/data/news_cache.db.

    Writes the rich schema SearchToolkit expects (articles + article_tickers +
    articles_fts, with topic_label / seed_section / content_text / tickers_json).
    NewsAgent then reads the same DB, identical to backtest's news handling.

    - 5 sections: chứng khoán, BĐS, doanh nghiệp, TCQT, vĩ mô
    - 3 pages per section
    - FOMO scoring disabled (score_fomo → 0)
    - TTL: skip if last crawl was within NEWS_CRAWL_TTL_SECONDS
    """
    flag = _load_sync_flag(NEWS_SYNC_FLAG_PATH)
    now = time.time()
    last = float(flag.get("ts") or 0)
    if not force and (now - last) < NEWS_CRAWL_TTL_SECONDS:
        return {"status": "skipped", "reason": "cache_fresh", "added": 0}

    today_iso = date.today().isoformat()
    t0 = time.time()

    # If the cache was created by the old lightweight crawler, schema is
    # incompatible — drop it so init_db rebuilds with tracking_news's schema.
    if _legacy_news_cache_schema(NEWS_CACHE_DB_PATH):
        try:
            NEWS_CACHE_DB_PATH.unlink()
        except Exception:
            pass

    window_start = (date.fromisoformat(today_iso) - timedelta(days=NEWS_WINDOW_DAYS - 1)).isoformat()
    os.environ["INGEST_DATE_FROM"] = window_start
    os.environ["INGEST_DATE_TO"] = today_iso

    error: Optional[str] = None
    try:
        _patch_tracking_news(today_iso)
        from app.ingest import run_once as tn_run_once

        tn_run_once.main()
    except Exception as exc:  # pragma: no cover
        error = f"{type(exc).__name__}: {exc}"
        print(f"[market_service] tracking_news crawl failed: {error}")

    added = 0
    if NEWS_CACHE_DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(NEWS_CACHE_DB_PATH))
            try:
                added = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM articles WHERE published_date = ?",
                        (today_iso,),
                    ).fetchone()[0]
                )
            finally:
                conn.close()
        except Exception:
            pass

    flag["ts"] = now
    flag["last_added"] = added
    _save_sync_flag(NEWS_SYNC_FLAG_PATH, flag)

    return {
        "status": "error" if error else "ok",
        "error": error,
        "added": added,
        "sections": len(KEEP_CAFEF_SECTIONS),
        "pages_per_section": CAFEF_PAGES_PER_ZONE,
        "duration_s": round(time.time() - t0, 2),
    }


_NEWS_CRAWL_LOCK = asyncio.Lock()


async def crawl_news_lite_async(*, force: bool = False) -> Dict[str, Any]:
    # Serialize concurrent crawls. If two POST /api/analyze fire in parallel
    # (e.g. React Strict Mode double-effect in dev), the second waits here and
    # then short-circuits on the TTL check inside crawl_news_lite.
    async with _NEWS_CRAWL_LOCK:
        return await asyncio.to_thread(crawl_news_lite, force=force)


# ── Public: read news from app/data/news_cache.db ────────────────────────────
def get_recent_news(limit: int = 20) -> List[Dict[str, Any]]:
    """Most recent articles from app/data/news_cache.db (tracking_news schema)."""

    limit = max(1, min(100, int(limit)))
    if not NEWS_CACHE_DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(NEWS_CACHE_DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT title, url, source, category, published_at "
                "FROM articles ORDER BY published_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as exc:
        print(f"[market_service] news read failed: {exc}")
        return []
