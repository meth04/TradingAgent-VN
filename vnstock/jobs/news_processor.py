"""Batch process news to daily ticker sentiment time-series.

Usage examples:
- python -m vnstock.jobs.news_processor --ticker HPG --days 3 --dry-run
- python -m vnstock.jobs.news_processor --ticker HPG --days 3
- python -m vnstock.jobs.news_processor --ticker HPG --date 2026-03-13 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import List, Tuple

import pandas as pd

from config import paths
from tracking_news.app import summarizer as tsummarizer
from vnstock.database.repo import DataRepository

NEWS_DB_PATH = paths.news_db_path


@dataclass
class Article:
    id: int
    title: str
    content_text: str
    published_at: str
    source: str
    published_date: str
    fomo_score: float


@dataclass
class ClusterResult:
    title: str
    score: float
    confidence: float
    key_event: str
    size: int


class KimiJSONSummarizer:
    """Wrapper reusing tracking_news summarizer session with JSON-only prompt."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    async def _summarize(
        self, cluster_title: str, snippets: list[str], ticker: str
    ) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "Output ONLY valid JSON with keys score (float -1..1), confidence (0..1), "
                    "key_event (string). No markdown, no bullet, no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Ticker: {ticker}. Cluster representative: {cluster_title}.\n"
                    "Provide sentiment JSON for these titles/snippets:\n"
                    + "\n".join(snippets)
                ),
            },
        ]

        api_key = tsummarizer.os.getenv("CLIPROXY_API_KEY")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        session = await tsummarizer._get_session()  # type: ignore[attr-defined]
        async with session.post(
            tsummarizer.PROXY_URL,
            headers=headers,
            json={"model": tsummarizer.MODEL_NAME, "messages": messages},
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["choices"][0]["message"]["content"].strip()

    def summarize(self, cluster_title: str, snippets: list[str], ticker: str) -> str:
        return self.loop.run_until_complete(
            self._summarize(cluster_title, snippets, ticker)
        )

    def close(self) -> None:
        try:
            self.loop.run_until_complete(tsummarizer.close_session())
        except Exception:
            pass
        self.loop.close()


def normalize_title(title: str) -> str:
    """Normalize title for clustering by lowering and collapsing spaces."""
    return " ".join(title.lower().strip().split())


def fetch_articles_for_day(
    conn: sqlite3.Connection, ticker: str, day: str, limit: int
) -> list[Article]:
    query = (
        "SELECT a.id, a.title, a.content_text, a.published_at, a.source, a.published_date, "
        "a.fomo_score FROM articles a "
        "JOIN article_tickers t ON t.article_id = a.id "
        "WHERE t.ticker = ? AND a.published_date = ? "
        "ORDER BY ABS(a.fomo_score) DESC, a.id DESC LIMIT ?"
    )
    rows = conn.execute(query, (ticker, day, limit)).fetchall()
    return [
        Article(
            id=row["id"],
            title=row["title"],
            content_text=row["content_text"],
            published_at=row["published_at"],
            source=row["source"],
            published_date=row["published_date"],
            fomo_score=row["fomo_score"],
        )
        for row in rows
    ]


def cluster_articles(articles: list[Article], threshold: float) -> list[list[Article]]:
    """Greedy clustering on normalized titles using SequenceMatcher ratio."""
    clusters: list[list[Article]] = []
    reps: list[str] = []
    for article in articles:
        norm_title = normalize_title(article.title)
        assigned = False
        for idx, rep in enumerate(reps):
            if SequenceMatcher(None, norm_title, rep).ratio() >= threshold:
                clusters[idx].append(article)
                assigned = True
                break
        if not assigned:
            clusters.append([article])
            reps.append(norm_title)
    return clusters


def parse_json_response(
    raw: str, fallback_score: float, fallback_conf: float
) -> Tuple[float, float, str]:
    """Parse strict/loose JSON, clamp ranges, fallback to provided defaults."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and start < end:
            try:
                data = json.loads(raw[start : end + 1])
            except Exception:
                data = {}
        else:
            data = {}

    score = (
        float(data.get("score", fallback_score))
        if isinstance(data, dict)
        else fallback_score
    )
    conf = (
        float(data.get("confidence", fallback_conf))
        if isinstance(data, dict)
        else fallback_conf
    )
    key_event = (
        str(data.get("key_event"))
        if isinstance(data, dict) and data.get("key_event") is not None
        else "(no key event)"
    )

    score = max(-1.0, min(1.0, score))
    conf = max(0.0, min(1.0, conf))
    return score, conf, key_event


def aggregate_clusters(results: list[ClusterResult]) -> tuple[float, float, str]:
    if not results:
        return 0.0, 0.0, "No articles."

    weighted_scores: list[float] = []
    weighted_conf: list[float] = []
    weights: list[float] = []
    for res in results:
        weight = res.size * max(res.confidence, 0.05)
        weights.append(weight)
        weighted_scores.append(res.score * weight)
        weighted_conf.append(res.confidence * weight)

    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0, 0.0, "No valid weights."

    daily_score = sum(weighted_scores) / total_weight
    daily_conf = sum(weighted_conf) / total_weight

    ranked = sorted(results, key=lambda r: abs(r.score) * r.size, reverse=True)[:5]
    impact_lines = [
        f"[{res.score:.2f} | conf {res.confidence:.2f} | n={res.size}] {res.key_event}"
        for res in ranked
    ]
    return float(daily_score), float(daily_conf), "\n".join(impact_lines)


def build_snippets(articles: list[Article]) -> list[str]:
    """Construct bullet snippets for LLM prompt."""
    snippets: list[str] = []
    for art in articles:
        content = (art.content_text or "")[:500].replace("\n", " ")
        snippets.append(f"- {art.title}: {content}")
    return snippets


def process_day(
    conn: sqlite3.Connection,
    ticker: str,
    day: datetime,
    limit: int,
    similarity: float,
    dry_run: bool,
    summarizer: KimiJSONSummarizer,
    repo: DataRepository,
) -> None:
    day_str = day.strftime("%Y-%m-%d")
    articles = fetch_articles_for_day(conn, ticker, day_str, limit)
    print(f"\n📅 {day_str} | articles: {len(articles)}")

    if not articles:
        if not dry_run:
            repo.upsert_daily_sentiment(ticker, day, 0.0, 0.0, "No articles.")
        print("   No articles found.")
        return

    clusters = cluster_articles(articles, similarity)
    print(f"   Clusters: {len(clusters)} (threshold={similarity})")

    cluster_results: list[ClusterResult] = []
    for idx, cluster in enumerate(clusters, start=1):
        rep_title = cluster[0].title
        snippets = build_snippets(cluster)
        fomo_mean = sum(a.fomo_score for a in cluster) / max(len(cluster), 1)
        raw_resp = summarizer.summarize(rep_title, snippets, ticker)
        score, conf, key_event = parse_json_response(raw_resp, fomo_mean, 0.2)
        cluster_results.append(
            ClusterResult(
                title=rep_title,
                score=score,
                confidence=conf,
                key_event=key_event,
                size=len(cluster),
            )
        )
        print(
            f"   - Cluster {idx}: n={len(cluster)} | score={score:.2f} | conf={conf:.2f} | "
            f"key_event={key_event}"
        )

    daily_score, daily_conf, impact_summary = aggregate_clusters(cluster_results)
    print(
        f"   => Daily score={daily_score:.3f} | conf={daily_conf:.3f} | impact:\n"
        + "\n".join(f"      {line}" for line in impact_summary.splitlines())
    )

    if not dry_run:
        repo.upsert_daily_sentiment(
            ticker, day, daily_score, daily_conf, impact_summary
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch news → daily sentiment.")
    parser.add_argument("--ticker", required=True, help="VN30 ticker, e.g., HPG")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--date", help="Specific date YYYY-MM-DD")
    group.add_argument(
        "--days",
        type=int,
        default=1,
        help="Number of days back from ref-date (inclusive).",
    )
    parser.add_argument(
        "--ref-date",
        dest="ref_date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Reference date (YYYY-MM-DD) for --days window (inclusive).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write DB.")
    parser.add_argument("--limit", type=int, default=300, help="Max articles per day.")
    parser.add_argument(
        "--similarity", type=float, default=0.8, help="Title similarity ratio."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ticker = args.ticker.upper().strip()

    dates: List[datetime] = []
    if args.date:
        dates = [pd.to_datetime(args.date).to_pydatetime()]
    else:
        ref_date = pd.to_datetime(args.ref_date).to_pydatetime()
        days = max(args.days, 1)
        dates = [ref_date - timedelta(days=offset) for offset in range(days)]

    conn = sqlite3.connect(NEWS_DB_PATH)
    conn.row_factory = sqlite3.Row

    summarizer = KimiJSONSummarizer()
    repo = DataRepository()

    try:
        for day in dates:
            day_floor = day.replace(hour=0, minute=0, second=0, microsecond=0)
            process_day(
                conn=conn,
                ticker=ticker,
                day=day_floor,
                limit=args.limit,
                similarity=args.similarity,
                dry_run=args.dry_run,
                summarizer=summarizer,
                repo=repo,
            )
    finally:
        summarizer.close()
        repo.close()
        conn.close()


if __name__ == "__main__":
    main()
