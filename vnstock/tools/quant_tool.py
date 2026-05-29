"""Institutional Quant Model: five-factor alpha with momentum, flow, sentiment, value, quality."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict

import pandas as pd
import pandas_ta as ta

from vnstock.database.models import FinancialRatio
from vnstock.database.repo import DataRepository


@dataclass
class AlphaComponents:
    ema20: float = 0.0
    ema50: float = 0.0
    rsi14: float = 0.0
    atr14: float = 0.0
    foreign_flow_5d: float = 0.0
    sentiment_score: float = 0.0
    sentiment_conf: float = 0.0
    pe: float | None = None
    pb: float | None = None
    roe: float | None = None
    roa: float | None = None
    beta: float | None = None
    debt_equity: float | None = None
    revenue_yoy: float | None = None
    net_profit_yoy: float | None = None
    trailing_eps: float | None = None
    book_value_per_share: float | None = None


@dataclass
class AlphaResult:
    ticker: str
    ref_date: datetime
    momentum_score: float
    flow_score: float
    sentiment_score: float
    value_score: float
    quality_score: float
    atr: float
    alpha_score: float
    components: AlphaComponents


class QuantToolkit:
    def __init__(self) -> None:
        self.repo = DataRepository()

    def close(self) -> None:
        self.repo.close()

    @staticmethod
    def _ema(series: pd.Series, span: int) -> float:
        return float(series.ewm(span=span, adjust=False).mean().iloc[-1])

    @staticmethod
    def _rsi(series: pd.Series, period: int = 14) -> float:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / (loss.replace(0, 1e-9))
        return float(100 - (100 / (1 + rs)).iloc[-1])

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])

    @staticmethod
    def _normalize(value: float, min_v: float, max_v: float) -> float:
        if math.isfinite(value) and max_v != min_v:
            return max(0.0, min(1.0, (value - min_v) / (max_v - min_v)))
        return 0.0

    @staticmethod
    def _safe_ratio_attr(ratio: FinancialRatio | None, field_name: str) -> float | None:
        if ratio is None:
            return None
        value = getattr(ratio, field_name, None)
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    @staticmethod
    def _round_optional(value: float | None, digits: int = 4) -> float | None:
        if value is None or not math.isfinite(value):
            return None
        return round(float(value), digits)

    def _ratio_components(
        self,
        ticker: str,
        ref_date: datetime,
    ) -> tuple[FinancialRatio | None, AlphaComponents]:
        ratio = self.repo.get_latest_ratio(ticker, ref_date)
        components = AlphaComponents(
            pe=self._safe_ratio_attr(ratio, "pe"),
            pb=self._safe_ratio_attr(ratio, "pb"),
            roe=self._safe_ratio_attr(ratio, "roe"),
            roa=self._safe_ratio_attr(ratio, "roa"),
            beta=self._safe_ratio_attr(ratio, "beta"),
            debt_equity=self._safe_ratio_attr(ratio, "debt_equity"),
            revenue_yoy=self._safe_ratio_attr(ratio, "revenue_yoy"),
            net_profit_yoy=self._safe_ratio_attr(ratio, "net_profit_yoy"),
            trailing_eps=self._safe_ratio_attr(ratio, "trailing_eps"),
            book_value_per_share=self._safe_ratio_attr(ratio, "book_value_per_share"),
        )
        return ratio, components

    def _compute_components(
        self,
        df: pd.DataFrame,
        ticker: str,
        ref_date: datetime,
    ) -> tuple[AlphaComponents, float]:
        df = df.sort_values("date") if not df.empty else df
        if not df.empty:
            df = df[df["date"] <= ref_date]

        _ratio, components = self._ratio_components(ticker, ref_date)
        senti_score, senti_conf, _ = self.repo.get_decayed_sentiment(
            ticker, ref_date, days_back=30
        )
        components.sentiment_score = senti_score
        components.sentiment_conf = senti_conf

        if df.empty or len(df) < 60:
            return components, 0.0

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        components.ema20 = self._ema(close, 20)
        components.ema50 = self._ema(close, 50)
        components.rsi14 = self._rsi(close, 14)
        components.atr14 = self._atr(high, low, close, 14)

        macd_df = ta.macd(close, fast=12, slow=26, signal=9)
        macd_hist = (
            float(macd_df.iloc[-1]["MACDh_12_26_9"])
            if macd_df is not None and not macd_df.empty
            else 0.0
        )

        if "buy_foreign" in df.columns and "sell_foreign" in df.columns:
            net = df["buy_foreign"].fillna(0) - df["sell_foreign"].fillna(0)
            components.foreign_flow_5d = float(net.tail(5).sum())

        return components, macd_hist

    def _score_value(self, components: AlphaComponents) -> float:
        pe_score = 0.0
        pb_score = 0.0
        if components.pe is not None and components.pe > 0:
            pe_score = self._normalize(1.0 / components.pe, 0.0, 0.15)
        if components.pb is not None and components.pb > 0:
            pb_score = self._normalize(1.0 / components.pb, 0.0, 1.0)
        return (0.5 * pe_score) + (0.5 * pb_score)

    def _score_quality(self, components: AlphaComponents) -> float:
        if components.roe is not None and components.roe > 0:
            return self._normalize(components.roe, 0.0, 30.0)
        if components.roa is not None and components.roa > 0:
            return self._normalize(components.roa, 0.0, 15.0)
        return 0.0

    def calculate_alpha_score(self, ticker: str, ref_date: str) -> AlphaResult:
        ref_dt = pd.to_datetime(ref_date).to_pydatetime()
        df = self.repo.get_price_history(ticker, days=120, end_date=ref_dt)
        components, macd_hist = self._compute_components(df, ticker, ref_dt)

        momentum = 0.0
        flow_score = 0.0
        if components.ema50 > 0:
            ema_spread = components.ema20 - components.ema50
            trend_ok = ema_spread > 0
            base_momentum = 0.5 * self._normalize(
                ema_spread,
                -0.05 * components.ema50,
                0.05 * components.ema50,
            ) + 0.5 * (components.rsi14 / 100)
            macd_penalty = 0.2 if macd_hist < 0 else 0.0
            momentum = max(0.0, base_momentum - macd_penalty)
            if not trend_ok:
                momentum *= 0.2

            vol_mean = float(df["volume"].tail(20).mean() or 1)
            flow_norm = components.foreign_flow_5d / (vol_mean + 1e-9)
            flow_score = self._normalize(flow_norm, -0.02, 0.02)

        sent_score = max(-1.0, min(1.0, components.sentiment_score))
        sent_weighted = (sent_score + 1) / 2
        sent_weighted *= max(0.2, min(1.0, components.sentiment_conf))

        value_score = self._score_value(components)
        quality_score = self._score_quality(components)

        alpha = (
            (0.30 * momentum)
            + (0.20 * flow_score)
            + (0.20 * sent_weighted)
            + (0.15 * value_score)
            + (0.15 * quality_score)
        )
        alpha_pct = round(alpha * 100, 2)

        return AlphaResult(
            ticker=ticker,
            ref_date=ref_dt,
            momentum_score=momentum,
            flow_score=flow_score,
            sentiment_score=sent_weighted,
            value_score=value_score,
            quality_score=quality_score,
            atr=components.atr14,
            alpha_score=alpha_pct,
            components=components,
        )

    def quick_report(self, ticker: str, ref_date: str) -> Dict[str, float | None | str]:
        res = self.calculate_alpha_score(ticker, ref_date)
        return {
            "ticker": res.ticker,
            "ref_date": res.ref_date.strftime("%Y-%m-%d"),
            "alpha_score": res.alpha_score,
            "momentum_score": round(res.momentum_score, 4),
            "flow_score": round(res.flow_score, 4),
            "sentiment_score": round(res.sentiment_score, 4),
            "value_score": round(res.value_score, 4),
            "quality_score": round(res.quality_score, 4),
            "ema20": round(res.components.ema20, 4),
            "ema50": round(res.components.ema50, 4),
            "rsi14": round(res.components.rsi14, 4),
            "foreign_flow_5d": round(res.components.foreign_flow_5d, 4),
            "atr14": round(res.components.atr14, 4),
            "sentiment_conf": round(res.components.sentiment_conf, 4),
            "pe": self._round_optional(res.components.pe),
            "pb": self._round_optional(res.components.pb),
            "roe": self._round_optional(res.components.roe),
            "roa": self._round_optional(res.components.roa),
            "beta": self._round_optional(res.components.beta),
            "debt_equity": self._round_optional(res.components.debt_equity),
            "revenue_yoy": self._round_optional(res.components.revenue_yoy),
            "net_profit_yoy": self._round_optional(res.components.net_profit_yoy),
            "trailing_eps": self._round_optional(res.components.trailing_eps),
            "book_value_per_share": self._round_optional(res.components.book_value_per_share),
        }


if __name__ == "__main__":
    qt = QuantToolkit()
    print(qt.quick_report("HPG", datetime.now().strftime("%Y-%m-%d")))
    qt.close()
