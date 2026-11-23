from __future__ import annotations

from datetime import datetime
from typing import Any, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from .models import AgentLog, DailySentiment, FinancialRatio, MarketDataDaily, SessionLocal, Symbol


class DataRepository:
    def __init__(self):
        self.db: Session = SessionLocal()

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _build_market_record(ticker: str, row: pd.Series) -> MarketDataDaily:
        vol = int(row.get("volume", 0)) if not pd.isna(row.get("volume")) else 0
        buy_f = int(row.get("buy_foreign", 0)) if not pd.isna(row.get("buy_foreign")) else 0
        sell_f = int(row.get("sell_foreign", 0)) if not pd.isna(row.get("sell_foreign")) else 0
        return MarketDataDaily(
            ticker=ticker,
            date=row["date"],
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=vol,
            buy_foreign=buy_f,
            sell_foreign=sell_f,
        )

    def save_daily_data(self, ticker: str, df: pd.DataFrame) -> int:
        """
        Lưu DataFrame OHLCV + Foreign Flow vào DB.
        Hỗ trợ cả incremental sync lẫn backfill các khoảng ngày bị thiếu.
        """
        if df.empty:
            return 0

        normalized_dates = pd.to_datetime(df["date"])
        window_start = normalized_dates.min().to_pydatetime()
        window_end = normalized_dates.max().to_pydatetime()
        existing_dates = {
            pd.Timestamp(row[0]).to_pydatetime()
            for row in self.db.query(MarketDataDaily.date)
            .filter(
                MarketDataDaily.ticker == ticker,
                MarketDataDaily.date >= window_start,
                MarketDataDaily.date <= window_end,
            )
            .all()
        }

        count = 0
        new_records = []
        for _, row in df.iterrows():
            row_date = pd.to_datetime(row["date"]).to_pydatetime()
            if row_date in existing_dates:
                continue
            new_records.append(self._build_market_record(ticker, row))
            existing_dates.add(row_date)
            count += 1

        if new_records:
            self.db.add_all(new_records)
            self.db.commit()

        return count

    def replace_daily_data(self, ticker: str, df: pd.DataFrame) -> int:
        """Replace all stored daily OHLCV rows for one ticker with the provided snapshot."""
        try:
            self.db.query(MarketDataDaily).filter(MarketDataDaily.ticker == ticker).delete(
                synchronize_session=False
            )
            records = [self._build_market_record(ticker, row) for _, row in df.iterrows()]
            if records:
                self.db.add_all(records)
            self.db.commit()
            return len(records)
        except Exception:
            self.db.rollback()
            raise

    @staticmethod
    def _to_ratio_value(value: Any) -> float | None:
        if value is None or pd.isna(value):
            return None
        numeric = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric):
            return None
        return float(numeric)

    @staticmethod
    def _growth_pct(current: float | None, previous: float | None) -> float | None:
        if current is None or previous is None or previous == 0:
            return None
        return ((current - previous) / abs(previous)) * 100.0

    def replace_financial_ratios(self, ticker: str, records: list[dict[str, Any]]) -> int:
        """Replace all stored quarterly financial ratios for one ticker."""
        try:
            self.db.query(FinancialRatio).filter(FinancialRatio.ticker == ticker).delete(
                synchronize_session=False
            )
            ratio_rows = [FinancialRatio(**record) for record in records]
            if ratio_rows:
                self.db.add_all(ratio_rows)
            self.db.commit()
            return len(ratio_rows)
        except Exception:
            self.db.rollback()
            raise

    def save_financial_ratios(self, ticker: str, records: list[dict[str, Any]]) -> int:
        """Upsert quarterly financial ratios for one ticker."""
        if not records:
            return 0

        count = 0
        try:
            for record in records:
                quarter = str(record.get("quarter", "")).strip()
                if not quarter:
                    continue
                existing = (
                    self.db.query(FinancialRatio)
                    .filter(FinancialRatio.ticker == ticker, FinancialRatio.quarter == quarter)
                    .first()
                )
                if existing:
                    for key, value in record.items():
                        setattr(existing, key, value)
                else:
                    self.db.add(FinancialRatio(**record))
                count += 1
            self.db.commit()
            return count
        except Exception:
            self.db.rollback()
            raise

    def get_latest_ratio(self, ticker: str, ref_date: datetime | str | None = None) -> FinancialRatio | None:
        """Return the latest quarterly ratio row up to the requested reference date."""
        try:
            query = self.db.query(FinancialRatio).filter(FinancialRatio.ticker == ticker)
            if ref_date is not None:
                cutoff = pd.to_datetime(ref_date).to_pydatetime()
                ref_quarter = f"{cutoff.year}-Q{((cutoff.month - 1) // 3) + 1}"
                query = query.filter(FinancialRatio.quarter <= ref_quarter)
            return query.order_by(FinancialRatio.quarter.desc()).first()
        except Exception as exc:
            print(f"⚠️ Lỗi lấy financial ratio {ticker}: {exc}")
            return None

    def upsert_symbol_metadata(self, ticker: str, metadata: dict[str, Any]) -> None:
        """Create or update symbol metadata used by quant and sector logic."""
        try:
            normalized_ticker = ticker.upper().strip()
            existing = self.db.query(Symbol).filter(Symbol.ticker == normalized_ticker).first()
            if existing is None:
                existing = Symbol(ticker=normalized_ticker)
                self.db.add(existing)
            for key, value in metadata.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def get_symbol(self, ticker: str) -> Symbol | None:
        """Return stored symbol metadata for one ticker."""
        try:
            normalized_ticker = ticker.upper().strip()
            return self.db.query(Symbol).filter(Symbol.ticker == normalized_ticker).first()
        except Exception as exc:
            print(f"⚠️ Lỗi lấy symbol {ticker}: {exc}")
            return None

    def resolve_sector_bucket(self, ticker: str) -> str:
        """Map ICB metadata into a stable coarse sector bucket."""
        symbol = self.get_symbol(ticker)
        if symbol is None:
            return "other"

        labels = [
            str(value).strip().lower()
            for value in [symbol.industry, symbol.icb_name2, symbol.icb_name3, symbol.icb_name4]
            if value
        ]
        text = " | ".join(labels)
        if any(keyword in text for keyword in ["ngân hàng", "bank"]):
            return "banking"
        if any(keyword in text for keyword in ["bất động sản", "real estate", "real_estate"]):
            return "real_estate"
        if any(keyword in text for keyword in ["công nghệ", "phần mềm", "technology", "software"]):
            return "technology"
        if any(keyword in text for keyword in ["tài nguyên", "vật liệu", "materials", "steel", "chemical"]):
            return "materials"
        if any(keyword in text for keyword in ["dầu khí", "energy", "oil", "gas", "tiện ích", "utility"]):
            return "energy"
        if any(keyword in text for keyword in ["bán lẻ", "thực phẩm", "consumer", "retail", "beverage"]):
            return "consumer"
        if any(keyword in text for keyword in ["vận tải", "aviation", "airline", "transport"]):
            return "transport"
        if any(keyword in text for keyword in ["bảo hiểm", "insurance"]):
            return "insurance"
        if any(keyword in text for keyword in ["chứng khoán", "securities", "brokerage"]):
            return "securities"
        return "other"

    def save_agent_log(
        self, ticker: str, action: str, confidence: str, reason: str
    ) -> None:
        """Lưu kết quả quyết định của Risk Manager"""
        try:
            log = AgentLog(
                ticker=ticker,
                action=action,
                confidence=confidence,
                reason=reason,
                timestamp=datetime.now(),
            )
            self.db.add(log)
            self.db.commit()
        except Exception as exc:
            print(f"⚠️ Lỗi lưu log: {exc}")
            self.db.rollback()

    def get_price_history(
        self,
        ticker: str,
        days: int = 3650,
        *,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
    ) -> pd.DataFrame:
        """
        Lấy dữ liệu lịch sử chuẩn hóa cho Quant Tool.
        Bao gồm cả dữ liệu Khối ngoại (buy_foreign, sell_foreign).
        """
        try:
            query = self.db.query(MarketDataDaily).filter(MarketDataDaily.ticker == ticker)
            if start_date is not None:
                start_ts = pd.to_datetime(start_date).normalize()
                query = query.filter(MarketDataDaily.date >= start_ts.to_pydatetime())
            if end_date is not None:
                end_exclusive = (pd.to_datetime(end_date).normalize() + pd.Timedelta(days=1)).to_pydatetime()
                query = query.filter(MarketDataDaily.date < end_exclusive)
            if days > 0 and start_date is None and end_date is None:
                rows = query.order_by(MarketDataDaily.date.desc()).limit(days).all()
                results = sorted(rows, key=lambda row: row.date)
            else:
                results = query.order_by(MarketDataDaily.date.asc()).all()

            if not results:
                return pd.DataFrame()

            data = [
                {
                    "date": r.date,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                    "buy_foreign": r.buy_foreign,
                    "sell_foreign": r.sell_foreign,
                }
                for r in results
            ]

            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            cols = [
                "open",
                "high",
                "low",
                "close",
                "volume",
                "buy_foreign",
                "sell_foreign",
            ]
            for col in cols:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

            if days > 0 and (start_date is not None or end_date is not None):
                df = df.tail(days)

            return df.reset_index(drop=True)

        except Exception as exc:
            print(f"⚠️ Lỗi đọc DB {ticker}: {exc}")
            return pd.DataFrame()

    def upsert_daily_sentiment(
        self,
        ticker: str,
        day: datetime,
        daily_score: float,
        confidence: float,
        impact_summary: str,
    ) -> None:
        """Upsert daily sentiment for (date, ticker)."""
        try:
            existing = (
                self.db.query(DailySentiment)
                .filter(DailySentiment.ticker == ticker, DailySentiment.date == day)
                .first()
            )
            if existing:
                existing.daily_score = daily_score
                existing.confidence = confidence
                existing.impact_summary = impact_summary
            else:
                record = DailySentiment(
                    ticker=ticker,
                    date=day,
                    daily_score=daily_score,
                    confidence=confidence,
                    impact_summary=impact_summary,
                )
                self.db.add(record)
            self.db.commit()
        except Exception as exc:
            print(f"⚠️ Lỗi upsert sentiment: {exc}")
            self.db.rollback()

    def get_decayed_sentiment(
        self, ticker: str, ref_date: datetime, days_back: int = 5
    ) -> Tuple[float, float, int]:
        """
        Lấy sentiment suy giảm theo ngày: weight = 0.5 ** k
        Returns (decayed_score, decayed_confidence, days_used)
        """
        try:
            start_date = ref_date.replace(hour=0, minute=0, second=0, microsecond=0)
            results = (
                self.db.query(DailySentiment)
                .filter(
                    DailySentiment.ticker == ticker,
                    DailySentiment.date
                    >= start_date - pd.Timedelta(days=days_back - 1),
                    DailySentiment.date <= start_date,
                )
                .order_by(DailySentiment.date.desc())
                .all()
            )
            if not results:
                return 0.0, 0.0, 0

            weights = []
            scores = []
            confidences = []
            for row in results:
                days_diff = (start_date - row.date).days
                weight = 0.5**days_diff
                weights.append(weight)
                scores.append(row.daily_score if row.daily_score is not None else 0.0)
                confidences.append(
                    row.confidence if row.confidence is not None else 0.0
                )

            total_weight = sum(weights)
            if total_weight == 0:
                return 0.0, 0.0, 0

            weighted_score = sum(s * w for s, w in zip(scores, weights)) / total_weight
            weighted_conf = (
                sum(c * w for c, w in zip(confidences, weights)) / total_weight
            )
            return float(weighted_score), float(weighted_conf), len(results)
        except Exception as exc:
            print(f"⚠️ Lỗi lấy sentiment suy giảm: {exc}")
            return 0.0, 0.0, 0
