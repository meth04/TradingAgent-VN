"""FastMCP server exposing news query tools for tracking_news DB."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from app.db.conn import connect
from app.summarizer import summarize_for_agent

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - import guard
    print(f"Missing dependency: {exc}", file=sys.stderr)
    raise

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = os.getenv("NEWS_DB_PATH", str(PROJECT_ROOT / "data" / "news.db"))

NEWS_TOPICS = {"stocks", "business", "banking", "real_estate"}
MACRO_SECTIONS = {"vi-mo-dau-tu", "tai-chinh-quoc-te", "chinh-sach-moi"}
MACRO_TOPICS = {"macro_policy"}

DEFAULT_DAYS_BACK = 5
DEFAULT_SEARCH_LIMIT = 15
DEFAULT_TICKER_LIMIT = 10
DEFAULT_MACRO_LIMIT = 15
MAX_LIMIT = 200
SNIPPET_LEN = 200

mcp = FastMCP("VN News MCP")


def _clamp_limit(limit: int, default: int) -> int:
    if limit <= 0:
        return default
    return min(limit, MAX_LIMIT)


def _date_range(ref_date: str, days_back: int) -> tuple[str, str]:
    ref = dt.date.fromisoformat(ref_date)
    start = ref - dt.timedelta(days=days_back)
    return start.isoformat(), ref.isoformat()


def _agent_filters(agent_type: str) -> tuple[Sequence[str], Sequence[str]]:
    if agent_type == "macro":
        return tuple(MACRO_TOPICS), tuple(MACRO_SECTIONS)
    return tuple(NEWS_TOPICS), ()


def _build_base_query(
    date_from: str,
    date_to: str,
    topics: Sequence[str],
    sections: Sequence[str],
    include_content: bool,
) -> tuple[str, list[Any]]:
    fields = [
        "a.id",
        "a.title",
        "a.source",
        "a.published_date",
        "a.fomo_score",
        "a.tickers_json",
        "a.content_text" if include_content else "substr(a.content_text, 1, ?) as content_text",
    ]
    params: list[Any] = []
    if not include_content:
        params.append(SNIPPET_LEN)

    sql = [
        "SELECT",
        ",".join(fields),
        "FROM articles a",
    ]

    where = ["a.published_date BETWEEN ? AND ?"]
    params.extend([date_from, date_to])

    if topics:
        where.append("a.topic_label IN (" + ",".join(["?"] * len(topics)) + ")")
        params.extend(list(topics))

    if sections:
        where.append("a.seed_section IN (" + ",".join(["?"] * len(sections)) + ")")
        params.extend(list(sections))

    return "\n".join(sql), where, params


def _append_ticker_join(sql: str, where: list[str], params: list[Any], ticker: str) -> str:
    sql += "\nJOIN article_tickers t ON t.article_id = a.id"
    where.append("t.ticker = ?")
    params.append(ticker)
    return sql


def _append_fts(sql: str, where: list[str], params: list[Any], query: str) -> str:
    sql += "\nJOIN articles_fts ON articles_fts.rowid = a.id"
    where.append("articles_fts MATCH ?")
    params.append(query)
    return sql


def _finalize_sql(sql: str, where: list[str]) -> str:
    order = "ORDER BY a.published_date DESC, ABS(a.fomo_score) DESC, a.id DESC"
    if where:
        return sql + "\nWHERE " + " AND ".join(where) + "\n" + order
    return sql + "\n" + order


def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    """Convert sqlite rows to plain dicts for serialization."""

    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "id": row["id"],
                "title": row["title"],
                "source": row["source"],
                "published_date": row["published_date"],
                "fomo_score": row["fomo_score"],
                "tickers_json": row["tickers_json"],
                "content_text": row["content_text"],
            }
        )
    return results


async def _maybe_summarize(
    articles: list[dict[str, Any]], agent_type: str, ticker: str | None, summarize: bool
) -> str:
    if not summarize:
        return "\n".join(_format_article_lines(articles))
    summary = await summarize_for_agent(articles, agent_type, ticker)
    return summary


def _format_article_lines(articles: list[dict[str, Any]]) -> list[str]:
    lines = []
    for art in articles:
        tickers = art.get("tickers_json") or "[]"
        lines.append(
            f"[{art['published_date']}] {art['source']} | {art['title']} | "
            f"fomo={art['fomo_score']:.2f} | tickers={tickers}\n"
            f"{art['content_text']}"
        )
    return lines


@mcp.tool()
async def search_news(
    query: str,
    ref_date: str,
    days_back: int = DEFAULT_DAYS_BACK,
    agent_type: str = "news",
    ticker: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    include_content: bool = False,
    summarize: bool = True,
) -> str:
    limit = _clamp_limit(limit, DEFAULT_SEARCH_LIMIT)
    topics, sections = _agent_filters(agent_type)
    date_from, date_to = _date_range(ref_date, days_back)

    sql, where, params = _build_base_query(date_from, date_to, topics, sections, include_content)

    if ticker:
        sql = _append_ticker_join(sql, where, params, ticker)

    if query:
        sql = _append_fts(sql, where, params, query)

    sql = _finalize_sql(sql, where) + f"\nLIMIT {limit}"

    rows = DB.execute(sql, params).fetchall()
    articles = _rows_to_dicts(rows)
    return await _maybe_summarize(articles, agent_type, ticker, summarize)


@mcp.tool()
async def get_article_content(article_id: int) -> str:
    row = DB.execute(
        "SELECT id, title, source, published_date, fomo_score, tickers_json, content_text "
        "FROM articles WHERE id = ?",
        (article_id,),
    ).fetchone()
    if row is None:
        return "Article not found"
    art = _rows_to_dicts([row])[0]
    return "\n".join(_format_article_lines([art]))


@mcp.tool()
async def get_news_by_ticker(
    ticker: str,
    ref_date: str,
    days_back: int = DEFAULT_DAYS_BACK,
    limit: int = DEFAULT_TICKER_LIMIT,
    min_fomo_score: float | None = None,
    summarize: bool = True,
) -> str:
    limit = _clamp_limit(limit, DEFAULT_TICKER_LIMIT)
    date_from, date_to = _date_range(ref_date, days_back)

    sql, where, params = _build_base_query(date_from, date_to, (), (), False)
    sql = _append_ticker_join(sql, where, params, ticker)

    if min_fomo_score is not None:
        where.append("ABS(a.fomo_score) >= ?")
        params.append(min_fomo_score)

    sql = _finalize_sql(sql, where) + f"\nLIMIT {limit}"

    rows = DB.execute(sql, params).fetchall()
    articles = _rows_to_dicts(rows)
    return await _maybe_summarize(articles, "news", ticker, summarize)


@mcp.tool()
async def get_macro_news(
    ref_date: str,
    days_back: int = DEFAULT_DAYS_BACK,
    limit: int = DEFAULT_MACRO_LIMIT,
    summarize: bool = True,
) -> str:
    limit = _clamp_limit(limit, DEFAULT_MACRO_LIMIT)
    topics, sections = _agent_filters("macro")
    date_from, date_to = _date_range(ref_date, days_back)

    sql, where, params = _build_base_query(date_from, date_to, topics, sections, False)
    sql = _finalize_sql(sql, where) + f"\nLIMIT {limit}"

    rows = DB.execute(sql, params).fetchall()
    articles = _rows_to_dicts(rows)
    return await _maybe_summarize(articles, "macro", None, summarize)


@mcp.tool()
async def get_db_stats() -> str:
    total = DB.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    min_date = DB.execute("SELECT MIN(published_date) FROM articles").fetchone()[0]
    max_date = DB.execute("SELECT MAX(published_date) FROM articles").fetchone()[0]
    per_source = DB.execute(
        "SELECT source, COUNT(*) as cnt FROM articles GROUP BY source ORDER BY cnt DESC"
    ).fetchall()
    per_topic = DB.execute(
        "SELECT topic_label, COUNT(*) as cnt FROM articles GROUP BY topic_label ORDER BY cnt DESC"
    ).fetchall()

    lines = [
        f"total={total}",
        f"range={min_date}..{max_date}",
        "per_source=" + ", ".join(f"{r['source']}:{r['cnt']}" for r in per_source),
        "per_topic=" + ", ".join(f"{r['topic_label']}:{r['cnt']}" for r in per_topic),
    ]
    return "\n".join(lines)


async def _shutdown() -> None:
    if DB:
        DB.close()


def _init_db() -> sqlite3.Connection:
    con = connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL;")
    return con


DB = _init_db()


if __name__ == "__main__":
    print("🚀 VN News MCP Ready", file=sys.stderr)
    mcp.run()
