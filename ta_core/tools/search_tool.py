from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from datetime import date, timedelta
from typing import Any, Dict, List, Sequence

from config import paths

# Ensure tracking_news is importable from any cwd
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", ".."))
TN_PATH = os.path.join(BASE_DIR, "tracking_news")
if TN_PATH not in sys.path:
    sys.path.append(TN_PATH)

NEWS_DB_PATH = str(paths.news_db_path)

MAX_RESULTS = 200
NEWS_TOPICS = {"stocks", "business", "banking", "real_estate"}
MACRO_SECTIONS = {"vi-mo-dau-tu", "tai-chinh-quoc-te", "chinh-sach-moi"}


class SearchToolkit:
    """SQLite-backed search over tracking_news articles with summarization."""

    @staticmethod
    def _ensure_db_path() -> str:
        if not os.path.exists(NEWS_DB_PATH):
            raise FileNotFoundError(
                f"tracking_news DB not found at {NEWS_DB_PATH}. Run crawler/backfill first."
            )
        return NEWS_DB_PATH

    @staticmethod
    def _build_date_range(ref_date: str | None, days_back: int) -> tuple[str, str]:
        # CRITICAL: ref_date must be provided in backtest mode to prevent lookahead bias
        if ref_date is None:
            raise ValueError(
                "ref_date is required to prevent lookahead bias. "
                "In backtest mode, never query future news by falling back to today()."
            )
        end_date = date.fromisoformat(ref_date)
        start_date = end_date - timedelta(days=days_back)
        return start_date.isoformat(), end_date.isoformat()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {k: row[k] for k in row.keys()}

    @staticmethod
    def _query_sql(sql: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
        con = sqlite3.connect(SearchToolkit._ensure_db_path())
        con.row_factory = sqlite3.Row
        try:
            cur = con.execute(sql, params)
            return [SearchToolkit._row_to_dict(r) for r in cur.fetchall()]
        finally:
            con.close()

    @staticmethod
    async def _fetch_articles(
        *,
        agent_type: str,
        query: str | None,
        ticker: str | None,
        ref_date: str | None,
        limit: int,
        days_back: int,
    ) -> List[Dict[str, Any]]:
        limit = max(1, min(limit, MAX_RESULTS))
        start_date, end_date = SearchToolkit._build_date_range(ref_date, days_back)

        joins: list[str] = []
        where: list[str] = ["a.published_date BETWEEN ? AND ?"]
        params: list[Any] = [start_date, end_date]

        if agent_type == "macro":
            where.append(
                "(a.topic_label = 'macro_policy' OR a.seed_section IN (?,?,?))"
            )
            params.extend(sorted(MACRO_SECTIONS))
        else:
            where.append("a.topic_label IN (?,?,?,?)")
            params.extend(sorted(NEWS_TOPICS))

        if ticker:
            joins.append("JOIN article_tickers at ON at.article_id = a.id")
            where.append("at.ticker = ?")
            params.append(ticker.upper())

        if query:
            joins.append("JOIN articles_fts ON articles_fts.rowid = a.id")
            where.append("articles_fts MATCH ?")
            params.append(query)

        sql = (
            "SELECT "
            "a.id, a.title, a.source, a.category, a.published_date, a.published_at, "
            "a.content_text, a.fomo_score, a.tickers_json "
            "FROM articles a "
            + " ".join(joins)
            + " WHERE "
            + " AND ".join(where)
            + " ORDER BY a.published_date DESC, abs(a.fomo_score) DESC, a.id DESC "
            + "LIMIT ?"
        )
        params.append(limit)

        results = await asyncio.to_thread(SearchToolkit._query_sql, sql, params)

        # Fallback: if ticker-based search returns nothing, retry with FTS query using ticker string
        if ticker and not results:
            fts_sql = (
                "SELECT a.id, a.title, a.source, a.category, a.published_date, a.published_at, "
                "a.content_text, a.fomo_score, a.tickers_json "
                "FROM articles a "
                "JOIN articles_fts ON articles_fts.rowid = a.id "
                "WHERE a.published_date BETWEEN ? AND ? AND articles_fts MATCH ? "
                "AND a.topic_label IN (?,?,?,?) "
                "ORDER BY a.published_date DESC, abs(a.fomo_score) DESC, a.id DESC LIMIT ?"
            )
            fts_params = [start_date, end_date, ticker.upper(), *sorted(NEWS_TOPICS), limit]
            results = await asyncio.to_thread(SearchToolkit._query_sql, fts_sql, fts_params)

        return results

    @staticmethod
    async def _summarize(articles: List[Dict[str, Any]], agent_type: str, ticker: str | None) -> str:
        if not articles:
            return "Không tìm thấy bài viết phù hợp."

        try:
            # Lazy import to keep vnstock independent
            from tracking_news.app.summarizer import summarize_for_agent

            return await summarize_for_agent(articles, agent_type=agent_type, ticker=ticker)
        except Exception as exc:  # noqa: BLE001
            snippets = [
                f"- {a.get('published_date')}: {a.get('title', '')} | {a.get('content_text', '')[:240]}"
                for a in articles[:5]
            ]
            return (
                "Bộ tóm tắt tạm thời không khả dụng, đang dùng các trích đoạn gốc. "
                f"Lý do: {exc}\n" + "\n".join(snippets)
            )

    @staticmethod
    async def search_news(
        query: str,
        *,
        ref_date: str | None,
        ticker: str | None,
        limit: int = 5,
        days_back: int = 10,
    ) -> str:
        articles = await SearchToolkit._fetch_articles(
            agent_type="news",
            query=query,
            ticker=ticker,
            ref_date=ref_date,
            limit=limit,
            days_back=days_back,
        )
        # keep top 5 for summarization speed
        articles = articles[:5]
        return await SearchToolkit._summarize(articles, agent_type="news", ticker=ticker)

    @staticmethod
    async def search_macro(
        *,
        ref_date: str | None,
        limit: int = 5,
        days_back: int = 5,
    ) -> str:
        articles = await SearchToolkit._fetch_articles(
            agent_type="macro",
            query=None,
            ticker=None,
            ref_date=ref_date,
            limit=limit,
            days_back=days_back,
        )
        articles = articles[:5]
        return await SearchToolkit._summarize(articles, agent_type="macro", ticker=None)
