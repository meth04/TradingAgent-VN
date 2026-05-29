"""Configure sys.path, env vars, and asyncio policy before any project imports."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Project root is sandbox/, two parents up from this file (sandbox/app/backend/bootstrap.py).
ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "app"
APP_DATA_DIR = APP_DIR / "data"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
(APP_DATA_DIR / "history").mkdir(parents=True, exist_ok=True)
(APP_DATA_DIR / "price_cache").mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# News DB: force both `config.paths.news_db_path` (vnstock/tools/search_tool.py
# reads this at module import) and `tracking_news.app.config.NEWS_DB_PATH` to
# point at the app-owned cache. The crawler writes here and SearchToolkit
# (used by NewsAgent) reads here — so news the user just crawled is what the
# agent actually analyzes, identical to how backtest reads `data/news.db`.
# ---------------------------------------------------------------------------
os.environ["NEWS_DB_PATH"] = str(APP_DATA_DIR / "news_cache.db")
# Defaults for the tracking_news ingest pipeline. crawl_news_lite() additionally
# patches INGEST_DATE_FROM/TO at call time to today's date.
os.environ.setdefault("MAX_PAGES_PER_SECTION", "3")
os.environ.setdefault("MAX_EXTRA_PAGES_PER_SECTION", "3")
os.environ.setdefault("ENABLED_SOURCES", "cafef")
os.environ.setdefault("CAFEF_ONLY_MODE", "1")
os.environ.setdefault("CAFEF_ONLY_ARTICLE_FETCH_WORKERS", "6")
os.environ.setdefault("CAFEF_ONLY_ARTICLE_RATE_LIMIT_SECONDS", "0.0")

# ---------------------------------------------------------------------------
# Force every model name to gpt-5.2, served by a local proxy.
# Must run BEFORE config.py and vnstock/core/llm.py are imported, because both
# read these env vars at module-import time.
# ---------------------------------------------------------------------------
LLM_MODEL_OVERRIDE = "gpt-5.2"
LLM_BASE_URL = "http://127.0.0.1:8317/v1"
LLM_API_KEY = "sk-my-key-is-empty"

os.environ["CLIPROXY_BASE_URL"] = LLM_BASE_URL
os.environ["CLIPROXY_API_KEY"] = LLM_API_KEY
# vnstock/core/llm.py reads GPT_MODEL or PRIMARY_MODEL for the default.
os.environ["GPT_MODEL"] = LLM_MODEL_OVERRIDE
os.environ["PRIMARY_MODEL"] = LLM_MODEL_OVERRIDE
# config.ModelConfig fields (each agent tier).
for _key in (
    "FINANCIAL_MODEL",
    "NEWS_MODEL",
    "T2_MACRO", "T2_MACRO_PRIMARY",
    "T2_NEWS", "T2_NEWS_PRIMARY",
    "T2_FINANCIAL", "T2_FINANCIAL_PRIMARY",
    "T2_TECHNICAL", "T2_TECHNICAL_PRIMARY",
    "T2_QUANT", "T2_QUANT_PRIMARY",
    "T3_DEBATE", "T3_DEBATE_PRIMARY",
    "T3_ARGUMENT", "T3_ARGUMENT_PRIMARY",
    "T4_CIO", "T4_CIO_PRIMARY",
    "DAILY_REPORT", "DAILY_REPORT_PRIMARY",
):
    os.environ[_key] = LLM_MODEL_OVERRIDE

# Match run.py path layout (NOT including cognitive_trading itself, since its config
# shadows the root one). cognitive_trading is imported via the package name.
for extra in (ROOT, ROOT / "vnstock", ROOT / "tracking_news"):
    extra_str = str(extra)
    if extra_str not in sys.path:
        sys.path.insert(0, extra_str)

# ---------------------------------------------------------------------------
# Disable chain-of-thought for FinancialAgent. Its prompt already carries a
# 16k-char cached report; adding a CoT preamble pushes input past 20k tokens
# and balloons response time to ~10 min on gpt-5.2 (~25x the other agents).
# We patch only the financial_agent module's bound reference so Macro/News/
# Technical/Quant keep their CoT.
# ---------------------------------------------------------------------------
try:
    import vnstock.agents.financial_agent as _fa_mod  # noqa: E402

    _fa_mod.TEXT_COT_PREFIX = ""
except Exception:
    pass

# ---------------------------------------------------------------------------
# News fallback (3 tiers):
#   Tier 1: same-day news for the ticker (freshest).
#   Tier 2: same ticker, last 3 days.
#   Tier 3: macro / market context (no ticker filter, last 5 days) — so when
#           there's no company-specific news at all, the agent still reasons
#           against current market backdrop instead of seeing an empty string.
# Only widens DB queries — does NOT trigger extra crawl.
# ---------------------------------------------------------------------------
try:
    from vnstock.tools.search_tool import SearchToolkit as _ST  # noqa: E402

    _orig_search_news = _ST.search_news
    _orig_search_macro = _ST.search_macro

    def _is_empty(s):
        return not isinstance(s, str) or "Không tìm thấy bài viết phù hợp" in s

    async def _search_news_with_fallback(
        query, *, ref_date, ticker, limit=5, days_back=10
    ):
        # Tier 1: same-day.
        result = await _orig_search_news(
            query, ref_date=ref_date, ticker=ticker, limit=limit, days_back=0
        )
        if _is_empty(result):
            # Tier 2: last 3 days, same ticker.
            result = await _orig_search_news(
                query, ref_date=ref_date, ticker=ticker, limit=limit, days_back=3
            )
        if _is_empty(result):
            # Tier 3: market/macro context (no ticker filter, last 5 days).
            macro = await _orig_search_macro(
                ref_date=ref_date, limit=limit, days_back=5
            )
            if not _is_empty(macro):
                result = (
                    f"(Không có tin riêng về {ticker} trong cửa sổ gần đây. "
                    f"Dùng bối cảnh thị trường/vĩ mô để tham chiếu:)\n\n{macro}"
                )
        return result

    _ST.search_news = staticmethod(_search_news_with_fallback)
except Exception:
    pass

# ---------------------------------------------------------------------------
# Quiet autogen's extremely verbose INFO logging. The Bull/Bear debate engine
# publishes every GroupChat message 4-6x as full JSON, which floods the backend
# log (hundreds of lines per debate). We only care about WARNING+ from it.
# ---------------------------------------------------------------------------
import logging  # noqa: E402

for _noisy in ("autogen_core", "autogen_core.events", "autogen_agentchat"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass
    # vnstock agents print emojis to stdout/stderr (e.g. "🤖 [Quant Agent]"),
    # which crashes on Windows' default cp1252 console. Reconfigure to UTF-8
    # so those prints don't propagate as exceptions into the agent task.
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
