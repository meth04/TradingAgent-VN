"""Pack deterministic, ref-date-safe planner contexts for each cognitive_trading ticker."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Mapping

from cognitive_trading.memory.episodic_store import EpisodicStore

import pandas as pd
import pandas_ta as ta

from vnstock.agents.financial_agent import FinancialAgent
from vnstock.tools.market_tool import MarketToolkit
from vnstock.tools.quant_tool import QuantToolkit
from vnstock.tools.search_tool import SearchToolkit


_FINANCIAL_AGENT = FinancialAgent()


def _to_timestamp(ref_date: str | date | datetime) -> pd.Timestamp:
    if isinstance(ref_date, pd.Timestamp):
        return ref_date.normalize()
    if isinstance(ref_date, datetime):
        return pd.Timestamp(ref_date).normalize()
    if isinstance(ref_date, date):
        return pd.Timestamp(ref_date.isoformat()).normalize()
    return pd.Timestamp(ref_date).normalize()


def _filter_history(df: pd.DataFrame, ref_ts: pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return df
    filtered = df.copy()
    filtered["date"] = pd.to_datetime(filtered["date"])
    filtered = filtered[filtered["date"] <= ref_ts]
    filtered = filtered.sort_values("date")
    return filtered.reset_index(drop=True)


def _scale_to_vnd(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value) * 1000.0, 4)


def _article_summary(articles: list[dict[str, Any]], limit: int = 3) -> dict[str, Any]:
    top_articles = []
    for article in articles[:limit]:
        top_articles.append(
            {
                "title": str(article.get("title", "")).strip(),
                "published_date": article.get("published_date"),
                "source": article.get("source"),
                "fomo_score": float(article.get("fomo_score", 0.0) or 0.0),
            }
        )
    summary = " | ".join(item["title"] for item in top_articles if item["title"])
    return {
        "count": len(articles),
        "top_articles": top_articles,
        "summary": summary or "Không tìm thấy bài viết phù hợp.",
    }


async def _financial_context(ticker: str, ref_date: str, max_chars: int = 4000) -> dict[str, Any]:
    return await _FINANCIAL_AGENT.get_financial_context(
        ticker=ticker,
        ref_date=ref_date,
        max_chars=max_chars,
    )


def _macd_context(df: pd.DataFrame) -> dict[str, float | str | None]:
    if df.empty:
        return {
            "line_vnd": None,
            "signal_vnd": None,
            "histogram_vnd": None,
            "signal": "unavailable",
        }

    macd_df = ta.macd(df["close"].astype(float), fast=12, slow=26, signal=9)
    if macd_df is None or macd_df.empty:
        return {
            "line_vnd": None,
            "signal_vnd": None,
            "histogram_vnd": None,
            "signal": "unavailable",
        }

    latest = macd_df.iloc[-1]
    line = float(latest["MACD_12_26_9"])
    signal = float(latest["MACDs_12_26_9"])
    histogram = float(latest["MACDh_12_26_9"])
    return {
        "line_vnd": _scale_to_vnd(line),
        "signal_vnd": _scale_to_vnd(signal),
        "histogram_vnd": _scale_to_vnd(histogram),
        "signal": "bullish" if line >= signal else "bearish",
    }


@dataclass(slots=True)
class ContextPacker:
    """Transform the event ledger into deterministic agent-ready context payloads."""

    search_toolkit: type[SearchToolkit]
    market_toolkit: type[MarketToolkit]
    quant_toolkit: QuantToolkit
    portfolio_context_provider: Callable[[str], dict[str, Any]] | None = None
    episodic_store: EpisodicStore | None = None
    recent_session_limit: int = 5
    news_lookback_days: int = 5
    macro_lookback_days: int = 5
    price_window_days: int = 60

    async def pack(
        self,
        event_ledger: Mapping[str, Any],
        ref_date: str | date | datetime | None = None,
    ) -> dict[str, dict[str, Any]]:
        ref_ts = _to_timestamp(ref_date or str(event_ledger["ref_date"]))
        ref_iso = ref_ts.date().isoformat()
        macro_window = self.search_toolkit._build_date_range(ref_iso, self.macro_lookback_days)
        macro_snapshot = event_ledger.get("macro_snapshot") if isinstance(event_ledger, Mapping) else None
        if isinstance(macro_snapshot, Mapping):
            macro_context = {
                "count": int(macro_snapshot.get("count") or 0),
                "top_articles": [
                    {"title": title, "published_date": None, "source": None, "fomo_score": 0.0}
                    for title in list(macro_snapshot.get("headlines") or [])[:3]
                ],
                "summary": " | ".join(list(macro_snapshot.get("headlines") or [])[:3]) or "Không tìm thấy bài viết phù hợp.",
                "window": {
                    "start": macro_window[0],
                    "end": macro_window[1],
                    "days_back": self.macro_lookback_days,
                },
            }
        else:
            macro_articles = await self.search_toolkit._fetch_articles(
                agent_type="macro",
                query=None,
                ticker=None,
                ref_date=ref_iso,
                limit=10,
                days_back=self.macro_lookback_days,
            )
            macro_context = {
                **_article_summary(macro_articles),
                "window": {
                    "start": macro_window[0],
                    "end": macro_window[1],
                    "days_back": self.macro_lookback_days,
                },
            }

        ticker_items = sorted(event_ledger.get("tickers", {}).items())
        if not ticker_items:
            return {}

        contexts = await asyncio.gather(
            *[
                self._pack_ticker(
                    ticker=ticker,
                    snapshot=dict(snapshot),
                    ref_ts=ref_ts,
                    macro_context=macro_context,
                )
                for ticker, snapshot in ticker_items
            ]
        )
        return {
            ticker: context
            for (ticker, _snapshot), context in zip(ticker_items, contexts, strict=False)
        }

    async def _pack_ticker(
        self,
        *,
        ticker: str,
        snapshot: dict[str, Any],
        ref_ts: pd.Timestamp,
        macro_context: dict[str, Any],
    ) -> dict[str, Any]:
        price_history = self.market_toolkit.get_price_data(
            ticker,
            days=self.price_window_days + 100,
            ref_date=ref_ts.date().isoformat(),
        )
        price_history = _filter_history(price_history, ref_ts)
        recent = price_history.tail(5)
        quant_result = self.quant_toolkit.calculate_alpha_score(ticker, ref_ts.date().isoformat())
        snapshot_news = snapshot.get("news", {}) if isinstance(snapshot, dict) else {}
        news_articles = []
        if not snapshot_news:
            news_articles = await self.search_toolkit._fetch_articles(
                agent_type="news",
                query=None,
                ticker=ticker,
                ref_date=ref_ts.date().isoformat(),
                limit=10,
                days_back=self.news_lookback_days,
            )

        price_context = {
            "latest_close_vnd": snapshot.get("latest_close_vnd"),
            "previous_close_vnd": snapshot.get("previous_close_vnd"),
            "recent_price_change_pct": snapshot.get("recent_price_change_pct"),
            "volume_context": snapshot.get("volume_context", {}),
            "recent_closes_vnd": [_scale_to_vnd(value) for value in recent["close"].tolist()],
            "recent_dates": [ts.strftime("%Y-%m-%d") for ts in recent["date"].tolist()],
            "sentiment": snapshot.get("sentiment", {}),
        }

        quant_context = {
            "alpha_score": round(float(quant_result.alpha_score), 4),
            "momentum_score": round(float(quant_result.momentum_score), 4),
            "flow_score": round(float(quant_result.flow_score), 4),
            "sentiment_score": round(float(quant_result.sentiment_score), 4),
            "value_score": round(float(quant_result.value_score), 4),
            "quality_score": round(float(quant_result.quality_score), 4),
            "rsi14": round(float(quant_result.components.rsi14), 4),
            "ema20_vnd": _scale_to_vnd(float(quant_result.components.ema20)),
            "ema50_vnd": _scale_to_vnd(float(quant_result.components.ema50)),
            "atr14_vnd": _scale_to_vnd(float(quant_result.components.atr14)),
            "foreign_flow_5d": round(float(quant_result.components.foreign_flow_5d), 4),
            "pe": quant_result.components.pe,
            "pb": quant_result.components.pb,
            "roe": quant_result.components.roe,
            "roa": quant_result.components.roa,
            "beta": quant_result.components.beta,
            "debt_equity": quant_result.components.debt_equity,
            "revenue_yoy": quant_result.components.revenue_yoy,
            "net_profit_yoy": quant_result.components.net_profit_yoy,
            "macd": _macd_context(price_history),
        }

        news_window = self.search_toolkit._build_date_range(ref_ts.date().isoformat(), self.news_lookback_days)
        if snapshot_news:
            news_context = {
                "count": int(snapshot_news.get("count") or 0),
                "top_articles": [
                    {"title": title, "published_date": None, "source": None, "fomo_score": 0.0}
                    for title in list(snapshot_news.get("headlines") or [])[:3]
                ],
                "summary": " | ".join(list(snapshot_news.get("headlines") or [])[:3]) or "Không tìm thấy bài viết phù hợp.",
                "window": {
                    "start": news_window[0],
                    "end": news_window[1],
                    "days_back": self.news_lookback_days,
                },
            }
        else:
            news_context = {
                **_article_summary(news_articles),
                "window": {
                    "start": news_window[0],
                    "end": news_window[1],
                    "days_back": self.news_lookback_days,
                },
            }

        portfolio_context = (
            self.portfolio_context_provider(ticker)
            if self.portfolio_context_provider is not None
            else {
                "available": False,
                "reason": "Portfolio snapshot provider chưa được cấu hình.",
            }
        )
        recent_sessions = []
        if self.episodic_store is not None:
            recent_sessions = self.episodic_store.get_recent_session_memory(
                ticker=ticker,
                current_ref_date=ref_ts.date().isoformat(),
                limit=self.recent_session_limit,
            )
        memory_summary_text = " | ".join(
            f"{item.get('trade_date')}: {item.get('action')} / pnl_t5={item.get('pnl_t5')} / alpha={item.get('alpha_vs_vn30')}"
            for item in recent_sessions
        )

        return {
            "price_context": price_context,
            "quant_context": quant_context,
            "news_context": news_context,
            "macro_context": macro_context,
            "financial_context": await _financial_context(ticker, ref_ts.date().isoformat()),
            "portfolio_context": portfolio_context,
            "recent_session_memory": {
                "count": len(recent_sessions),
                "recent_sessions": recent_sessions,
                "summary": memory_summary_text or "Chưa có trí nhớ ngắn hạn cho ticker này.",
            },
        }


async def pack_contexts(
    *,
    event_ledger: Mapping[str, Any],
    search_toolkit: type[SearchToolkit],
    market_toolkit: type[MarketToolkit],
    quant_toolkit: QuantToolkit,
    ref_date: str | date | datetime | None = None,
    news_lookback_days: int = 5,
    macro_lookback_days: int = 5,
    price_window_days: int = 60,
) -> dict[str, dict[str, Any]]:
    """Convenience wrapper for deterministic planner context packing."""

    packer = ContextPacker(
        search_toolkit=search_toolkit,
        market_toolkit=market_toolkit,
        quant_toolkit=quant_toolkit,
        news_lookback_days=news_lookback_days,
        macro_lookback_days=macro_lookback_days,
        price_window_days=price_window_days,
    )
    return await packer.pack(event_ledger=event_ledger, ref_date=ref_date)


__all__ = ["ContextPacker", "pack_contexts"]
