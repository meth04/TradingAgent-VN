"""Build a ref-date-safe market snapshot for planner inputs without lookahead."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from vnstock.database.repo import DataRepository
from vnstock.tools.market_tool import MarketToolkit
from vnstock.tools.quant_tool import QuantToolkit
from vnstock.tools.search_tool import SearchToolkit

_PRICE_MIN_VND = 1_000.0
_PRICE_MAX_VND = 5_000_000.0


def _to_timestamp(ref_date: str | date | datetime) -> pd.Timestamp:
    if isinstance(ref_date, pd.Timestamp):
        return ref_date.normalize()
    if isinstance(ref_date, datetime):
        return pd.Timestamp(ref_date).normalize()
    if isinstance(ref_date, date):
        return pd.Timestamp(ref_date.isoformat()).normalize()
    return pd.Timestamp(ref_date).normalize()


def _validate_vnd_price(raw_close: float) -> float:
    price_vnd = float(raw_close) * 1000.0
    if not (_PRICE_MIN_VND <= price_vnd <= _PRICE_MAX_VND):
        raise ValueError(f"price {price_vnd} out of valid VND range")
    return round(price_vnd, 4)


def _filter_history(df: pd.DataFrame, ref_ts: pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return df
    filtered = df.copy()
    filtered["date"] = pd.to_datetime(filtered["date"])
    filtered = filtered[filtered["date"] <= ref_ts]
    filtered = filtered.sort_values("date")
    return filtered.reset_index(drop=True)


def _volume_context(df: pd.DataFrame) -> dict[str, float | int | None]:
    latest_volume = int(df.iloc[-1]["volume"]) if not df.empty else 0
    avg_20d = float(df["volume"].tail(20).mean()) if not df.empty else 0.0
    ratio = latest_volume / avg_20d if avg_20d else None
    return {
        "latest": latest_volume,
        "avg_20d": round(avg_20d, 4),
        "ratio_to_20d": round(float(ratio), 4) if ratio is not None else None,
    }


def _headline_slice(articles: list[dict[str, Any]], limit: int = 3) -> list[str]:
    return [str(article.get("title", "")).strip() for article in articles[:limit] if article.get("title")]


def _safe_quant_preview(
    quant_toolkit: QuantToolkit,
    ticker: str,
    ref_ts: pd.Timestamp,
) -> dict[str, float | None]:
    report = quant_toolkit.quick_report(ticker, ref_ts.date().isoformat())
    return {
        "alpha_score": float(report.get("alpha_score", 0.0) or 0.0),
        "momentum_score": float(report.get("momentum_score", 0.0) or 0.0),
        "flow_score": float(report.get("flow_score", 0.0) or 0.0),
        "sentiment_score": float(report.get("sentiment_score", 0.0) or 0.0),
        "value_score": float(report.get("value_score", 0.0) or 0.0),
        "quality_score": float(report.get("quality_score", 0.0) or 0.0),
        "rsi14": float(report.get("rsi14", 0.0) or 0.0),
        "pe": report.get("pe"),
        "pb": report.get("pb"),
        "roe": report.get("roe"),
    }


@dataclass(slots=True)
class EventLedgerBuilder:
    """Assemble a JSON-serializable planning ledger at a single backtest ref_date."""

    repo: DataRepository
    search_toolkit: type[SearchToolkit]
    market_toolkit: type[MarketToolkit]
    quant_toolkit: QuantToolkit
    news_lookback_days: int = 5
    macro_lookback_days: int = 5
    sentiment_lookback_days: int = 5
    history_days: int = 90

    async def build(self, tickers: list[str], ref_date: str | date | datetime) -> dict[str, Any]:
        ref_ts = _to_timestamp(ref_date)
        ref_iso = ref_ts.date().isoformat()
        news_window = self.search_toolkit._build_date_range(ref_iso, self.news_lookback_days)
        macro_window = self.search_toolkit._build_date_range(ref_iso, self.macro_lookback_days)
        macro_articles = await self.search_toolkit._fetch_articles(
            agent_type="macro",
            query=None,
            ticker=None,
            ref_date=ref_iso,
            limit=50,
            days_back=self.macro_lookback_days,
        )
        macro_count = len(macro_articles)

        ledger: dict[str, Any] = {
            "ref_date": ref_iso,
            "windows": {
                "news": {
                    "start": news_window[0],
                    "end": news_window[1],
                    "days_back": self.news_lookback_days,
                },
                "macro": {
                    "start": macro_window[0],
                    "end": macro_window[1],
                    "days_back": self.macro_lookback_days,
                },
                "sentiment": {"days_back": self.sentiment_lookback_days},
            },
            "macro_snapshot": {
                "count": macro_count,
                "headlines": _headline_slice(macro_articles),
            },
            "tickers": {},
        }

        normalized_tickers = sorted({item.upper().strip() for item in tickers if item})
        if not normalized_tickers:
            return ledger

        batch_size = 10
        for batch_start in range(0, len(normalized_tickers), batch_size):
            batch = normalized_tickers[batch_start : batch_start + batch_size]
            snapshots = await asyncio.gather(
                *[
                    self._build_ticker_snapshot(
                        ticker=ticker,
                        ref_ts=ref_ts,
                        macro_count=macro_count,
                    )
                    for ticker in batch
                ],
                return_exceptions=True,
            )
            for ticker, snapshot in zip(batch, snapshots, strict=False):
                if isinstance(snapshot, Exception) or snapshot is None:
                    continue
                ledger["tickers"][ticker] = snapshot

        return ledger

    async def _build_ticker_snapshot(
        self,
        ticker: str,
        ref_ts: pd.Timestamp,
        macro_count: int,
    ) -> dict[str, Any] | None:
        history = self.repo.get_price_history(ticker, days=0)
        history = _filter_history(history, ref_ts)
        history = history.tail(self.history_days)
        if history.empty:
            return None

        latest_row = history.iloc[-1]
        prev_row = history.iloc[-2] if len(history) > 1 else None
        latest_close_vnd = _validate_vnd_price(float(latest_row["close"]))
        previous_close_vnd = (
            _validate_vnd_price(float(prev_row["close"])) if prev_row is not None else None
        )
        recent_change_pct = (
            ((float(latest_row["close"]) / float(prev_row["close"])) - 1.0) * 100.0
            if prev_row is not None and float(prev_row["close"]) != 0.0
            else None
        )

        sentiment_score, sentiment_confidence, sentiment_days = self.market_toolkit.get_news_sentiment(
            ticker,
            ref_ts.date().isoformat(),
            days_back=self.sentiment_lookback_days,
        )
        news_articles = await self.search_toolkit._fetch_articles(
            agent_type="news",
            query=None,
            ticker=ticker,
            ref_date=ref_ts.date().isoformat(),
            limit=50,
            days_back=self.news_lookback_days,
        )
        quant_report = _safe_quant_preview(self.quant_toolkit, ticker, ref_ts)

        return {
            "ticker": ticker,
            "latest_close_vnd": latest_close_vnd,
            "previous_close_vnd": previous_close_vnd,
            "recent_price_change_pct": round(float(recent_change_pct), 4)
            if recent_change_pct is not None
            else None,
            "volume_context": _volume_context(history),
            "sentiment": {
                "decayed_score": round(float(sentiment_score), 4),
                "confidence": round(float(sentiment_confidence), 4),
                "days_used": int(sentiment_days),
            },
            "news": {
                "count": len(news_articles),
                "headlines": _headline_slice(news_articles),
            },
            "macro": {"count": int(macro_count)},
            "quant_preview": {
                "alpha_score": float(quant_report["alpha_score"]),
                "momentum_score": float(quant_report["momentum_score"]),
                "flow_score": float(quant_report["flow_score"]),
                "sentiment_score": float(quant_report["sentiment_score"]),
                "value_score": float(quant_report["value_score"]),
                "quality_score": float(quant_report["quality_score"]),
                "rsi14": float(quant_report["rsi14"]),
                "pe": quant_report["pe"],
                "pb": quant_report["pb"],
                "roe": quant_report["roe"],
            },
        }


async def build_event_ledger(
    *,
    repo: DataRepository,
    search_toolkit: type[SearchToolkit],
    market_toolkit: type[MarketToolkit],
    quant_toolkit: QuantToolkit,
    tickers: list[str],
    ref_date: str | date | datetime,
    news_lookback_days: int = 5,
    macro_lookback_days: int = 5,
    sentiment_lookback_days: int = 5,
    history_days: int = 90,
) -> dict[str, Any]:
    """Convenience wrapper for building a planner event ledger."""

    builder = EventLedgerBuilder(
        repo=repo,
        search_toolkit=search_toolkit,
        market_toolkit=market_toolkit,
        quant_toolkit=quant_toolkit,
        news_lookback_days=news_lookback_days,
        macro_lookback_days=macro_lookback_days,
        sentiment_lookback_days=sentiment_lookback_days,
        history_days=history_days,
    )
    return await builder.build(tickers=tickers, ref_date=ref_date)


__all__ = ["EventLedgerBuilder", "build_event_ledger"]
