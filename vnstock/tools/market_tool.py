import sys
from pathlib import Path
import pandas as pd
import importlib

# Ensure external vnstock package is importable even when project name shadows it
_site_pkg = Path(__file__).resolve().parents[2] / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if _site_pkg.is_dir() and str(_site_pkg) not in sys.path:
    sys.path.insert(0, str(_site_pkg))

from vnstock.database.repo import DataRepository  # noqa: E402
from vnstock.jobs.crawler import MarketCrawler  # noqa: E402

# Optional import to trigger vnstock availability early (without hard fail)
try:
    importlib.import_module("vnstock")
except Exception:
    pass


class MarketToolkit:
    _price_cache = {}

    @staticmethod
    def _filter_to_ref_date(df: pd.DataFrame, ref_date: str | None) -> pd.DataFrame:
        if df.empty or ref_date is None:
            return df
        filtered = df.copy()
        filtered["date"] = pd.to_datetime(filtered["date"])
        end_exclusive = pd.to_datetime(ref_date).normalize() + pd.Timedelta(days=1)
        filtered = filtered[filtered["date"] < end_exclusive]
        return filtered.sort_values("date").reset_index(drop=True)

    @staticmethod
    def get_price_data(symbol: str, days: int = 730, ref_date: str | None = None) -> pd.DataFrame:
        """Lấy dữ liệu giá có cache và tôn trọng ref_date khi backtest."""
        symbol = symbol.upper().strip()

        if symbol in MarketToolkit._price_cache:
            last_time, cached_df = MarketToolkit._price_cache[symbol]
            if (pd.Timestamp.now() - last_time).total_seconds() < 3600:
                filtered_df = MarketToolkit._filter_to_ref_date(cached_df, ref_date)
                return filtered_df.tail(days)

        repo = DataRepository()
        try:
            df = repo.get_price_history(symbol, end_date=ref_date, days=days + 100)
            df = MarketToolkit._filter_to_ref_date(df, ref_date)

            if df.empty:
                crawler = MarketCrawler()
                try:
                    resolved_end = (
                        pd.to_datetime(ref_date).date().isoformat()
                        if ref_date is not None
                        else pd.Timestamp.now().date().isoformat()
                    )
                    lookback_days = max(days + 200, 550)
                    resolved_start = (
                        pd.to_datetime(resolved_end) - pd.Timedelta(days=lookback_days)
                    ).date().isoformat()
                    df_new = crawler._fetch_from_api(
                        symbol,
                        start_date=resolved_start,
                        end_date=resolved_end,
                    )
                    if not df_new.empty:
                        repo.save_daily_data(symbol, df_new)
                        df = repo.get_price_history(symbol, end_date=ref_date, days=days + 100)
                        df = MarketToolkit._filter_to_ref_date(df, ref_date)
                finally:
                    crawler.repo.close()

            if not df.empty:
                full_history = repo.get_price_history(symbol, days=0)
                MarketToolkit._price_cache[symbol] = (pd.Timestamp.now(), full_history)
                filtered_df = MarketToolkit._filter_to_ref_date(full_history, ref_date)
                return filtered_df.tail(days)
            return df

        except Exception as e:
            print(f"❌ Lỗi MarketTool: {e}", file=sys.stderr)
            return pd.DataFrame()
        finally:
            repo.close()

    @staticmethod
    def get_news_sentiment(
        symbol: str, ref_date: str, days_back: int = 5
    ) -> tuple[float, float, int]:
        """Lấy sentiment suy giảm theo ngày cho ticker."""
        repo = DataRepository()
        try:
            ref_dt = pd.to_datetime(ref_date)
            score, conf, days_used = repo.get_decayed_sentiment(
                symbol.upper(), ref_dt, days_back
            )
            return score, conf, days_used
        except Exception as exc:
            print(f"❌ Lỗi get_news_sentiment: {exc}", file=sys.stderr)
            return 0.0, 0.0, 0
        finally:
            repo.close()

    @staticmethod
    def get_technical_report(symbol: str, ref_date: str | None = None) -> str:
        """
        Phân tích kỹ thuật chuyên sâu và chỉ dùng dữ liệu tại hoặc trước ref_date.
        """
        df = MarketToolkit.get_price_data(symbol, days=365, ref_date=ref_date)
        if df.empty:
            return "⚠️ Không có dữ liệu giá."

        try:
            close = df["close"]
            high = df["high"]
            low = df["low"]

            # --- 1. TREND INDICATORS ---
            sma50 = close.rolling(50).mean()
            sma200 = close.rolling(200).mean()

            # Ichimoku Cloud (Cơ bản: Conversion & Base Line)
            nine_period_high = high.rolling(window=9).max()
            nine_period_low = low.rolling(window=9).min()
            tenkan_sen = (nine_period_high + nine_period_low) / 2

            twenty_six_period_high = high.rolling(window=26).max()
            twenty_six_period_low = low.rolling(window=26).min()
            kijun_sen = (twenty_six_period_high + twenty_six_period_low) / 2

            # --- 2. MOMENTUM INDICATORS ---
            # RSI
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / (loss.replace(0, 1e-10))
            rsi = 100 - (100 / (1 + rs))

            # Stochastic RSI (Nhạy hơn RSI thường)
            min_rsi = rsi.rolling(14).min()
            max_rsi = rsi.rolling(14).max()
            stoch_rsi = (rsi - min_rsi) / (max_rsi - min_rsi)

            # MACD
            k = close.ewm(span=12, adjust=False).mean()
            d = close.ewm(span=26, adjust=False).mean()
            macd = k - d
            signal = macd.ewm(span=9, adjust=False).mean()

            # --- 3. VOLATILITY & LEVELS ---
            # Bollinger Bands
            sma20 = close.rolling(20).mean()
            std = close.rolling(20).std()
            upper = sma20 + 2 * std
            lower = sma20 - 2 * std

            # Support & Resistance (Đơn giản: Đáy/Đỉnh 20 phiên)
            support_20d = low.rolling(20).min().iloc[-1]
            resistance_20d = high.rolling(20).max().iloc[-1]

            # --- TỔNG HỢP DỮ LIỆU HIỆN TẠI ---
            curr_price = close.iloc[-1]
            prev_price = close.iloc[-2] if len(close) > 1 else None
            prev_change_pct = (
                ((curr_price / prev_price) - 1) * 100 if prev_price not in (None, 0) else None
            )

            # Đánh giá Trend
            trend_long = "UPTREND" if curr_price > sma200.iloc[-1] else "DOWNTREND"
            trend_short = "BULLISH" if curr_price > sma50.iloc[-1] else "BEARISH"

            # Ichimoku Signal
            ichimoku_sig = (
                "Tích cực" if tenkan_sen.iloc[-1] > kijun_sen.iloc[-1] else "Tiêu cực"
            )

            # Oscillator Signals
            rsi_val = rsi.iloc[-1]
            stoch_val = stoch_rsi.iloc[-1]
            macd_val = macd.iloc[-1]
            sig_val = signal.iloc[-1]

            rsi_status = (
                "QUÁ MUA (>70)"
                if rsi_val > 70
                else "QUÁ BÁN (<30)"
                if rsi_val < 30
                else "Trung tính"
            )
            macd_status = "MUA (Cắt lên)" if macd_val > sig_val else "BÁN (Cắt xuống)"

            # Volume Analysis
            vol_mean = df["volume"].rolling(20).mean().iloc[-1]
            curr_vol = df["volume"].iloc[-1]
            vol_status = (
                "Đột biến"
                if curr_vol > 1.5 * vol_mean
                else "Thấp"
                if curr_vol < 0.7 * vol_mean
                else "Trung bình"
            )

            prev_price_text = f"{prev_price:,.0f} VND" if prev_price is not None else "Không có"
            prev_change_text = (
                f"{prev_change_pct:.2f}%" if prev_change_pct is not None else "Không có"
            )

            return f"""
            ### 📊 PHÂN TÍCH KỸ THUẬT NÂNG CAO: {symbol}

            **1. CẤU TRÚC GIÁ & XU HƯỚNG:**
            - Giá hiện tại: {curr_price:,.0f} VND ({trend_short} ngắn hạn / {trend_long} dài hạn)
            - Giá đóng cửa phiên trước: {prev_price_text}
            - Biến động so với hôm trước: {prev_change_text}
            - Hỗ trợ gần nhất (20d): {support_20d:,.0f}
            - Kháng cự gần nhất (20d): {resistance_20d:,.0f}
            - Ichimoku (Tenkan/Kijun): {ichimoku_sig}
            
            **2. ĐỘNG LƯỢNG (MOMENTUM):**
            - RSI (14): {rsi_val:.2f} [{rsi_status}]
            - Stoch RSI: {stoch_val:.2f} (0-1) - {"Vùng đáy" if stoch_val < 0.2 else "Vùng đỉnh" if stoch_val > 0.8 else "Trung gian"}
            - MACD: {macd_status} (Histogram: {macd_val - sig_val:.2f})
            
            **3. BIẾN ĐỘNG & THANH KHOẢN:**
            - Bollinger Bands: Giá đang ở {"TRÊN" if curr_price > upper.iloc[-1] else "DƯỚI" if curr_price < lower.iloc[-1] else "GIỮA"} dải băng.
            - Volume: {curr_vol:,.0f} ({vol_status} so với TB 20 phiên)
            """
        except Exception as e:
            return f"❌ Lỗi tính toán: {e}"
