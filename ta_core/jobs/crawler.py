import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from ta_core.data import market_data
from ta_core.database.models import init_db
from ta_core.database.repo import DataRepository

class MarketCrawler:
    """
    Class chịu trách nhiệm tải dữ liệu thị trường (OHLCV + Foreign Flow)
    và lưu vào Database thông qua DataRepository.
    """
    
    def __init__(self):
        # Danh sách VN30 (Có thể mở rộng thêm nếu muốn)
        self.watchlist = [
            "ACB", "BCM", "BID", "CTG", "DGC", "FPT", "GAS", "GVR", "HDB", "HPG",
            "LPB", "MBB", "MSN", "MWG", "PLX", "SAB", "SHB", "SSB", "SSI", "STB",
            "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
        ]
        self.benchmark_symbols = ["VN30", "VNINDEX"]
        self.repo = DataRepository()

    @staticmethod
    def _sleep_for_rpm(max_requests_per_minute: int) -> None:
        if max_requests_per_minute <= 0:
            return
        time.sleep(max(60.0 / max_requests_per_minute, 0.0))

    def _fetch_from_api(
        self,
        ticker: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        full_history: bool = False,
    ) -> pd.DataFrame:
        """Lấy dữ liệu (qua vn-market-data) + foreign flow cho window yêu cầu hoặc toàn bộ lịch sử."""
        try:
            resolved_end_date = end_date or datetime.now().strftime("%Y-%m-%d")

            from ta_core.database.models import MarketDataDaily

            if start_date is not None:
                resolved_start_date = start_date
            elif full_history:
                resolved_start_date = (datetime.now() - timedelta(days=3652)).strftime("%Y-%m-%d")
            else:
                last_record = (
                    self.repo.db.query(MarketDataDaily)
                    .filter(MarketDataDaily.ticker == ticker)
                    .order_by(MarketDataDaily.date.desc())
                    .first()
                )
                if last_record and last_record.date:
                    resolved_start_date = (last_record.date + timedelta(days=1)).strftime("%Y-%m-%d")
                else:
                    resolved_start_date = (datetime.now() - timedelta(days=3652)).strftime("%Y-%m-%d")

            if resolved_start_date > resolved_end_date:
                return pd.DataFrame()

            return self._fetch_quote_history(
                ticker,
                start_date=resolved_start_date,
                end_date=resolved_end_date,
                with_foreign_flow=True,
            )

        except Exception as exc:
            print(f"⚠️ Lỗi API nghiêm trọng khi tải {ticker}: {exc}")
            return pd.DataFrame()

    def _fetch_quote_history(
        self,
        ticker: str,
        *,
        start_date: str,
        end_date: str,
        with_foreign_flow: bool,
    ) -> pd.DataFrame:
        """Daily bars from vn-market-data, already in the shape the DB stores."""
        try:
            return market_data.get_daily_bars(
                ticker,
                start_date,
                end_date,
                with_foreign_flow=with_foreign_flow,
            )
        except Exception as exc:  # pylint: disable=broad-except
            print(f"⚠️ Lỗi tải giá {ticker}: {exc}")
            return pd.DataFrame()

    def _fetch_financial_ratios(self, ticker: str) -> list[dict[str, Any]]:
        try:
            return market_data.get_quarterly_ratios(ticker)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"⚠️ Lỗi tải chỉ số tài chính {ticker}: {exc}")
            return []

    def _sync_financial_ratios(self, ticker: str, *, replace_existing: bool) -> int:
        records = self._fetch_financial_ratios(ticker)
        if not records:
            return 0
        if replace_existing:
            return self.repo.replace_financial_ratios(ticker, records)
        return self.repo.save_financial_ratios(ticker, records)

    def _sync_symbol(
        self,
        ticker: str,
        *,
        replace_existing: bool,
        with_foreign_flow: bool,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        df = self._fetch_from_api(
            ticker,
            start_date=start_date,
            end_date=end_date,
            full_history=replace_existing,
        ) if with_foreign_flow else self._fetch_benchmark_from_api(
            ticker,
            start_date=start_date,
            end_date=end_date,
            full_history=replace_existing,
        )
        if df.empty:
            return 0
        if replace_existing:
            return self.repo.replace_daily_data(ticker, df)
        return self.repo.save_daily_data(ticker, df)

    def _fetch_symbol_overview(self, ticker: str) -> dict[str, Any]:
        try:
            overview = market_data.get_company_overview(ticker)
        except Exception:  # pylint: disable=broad-except
            return {}
        return {"ticker": ticker, **overview} if overview else {}

    def _sync_symbol_metadata(self, ticker: str) -> None:
        metadata = self._fetch_symbol_overview(ticker)
        if metadata:
            metadata.pop("ticker", None)
            self.repo.upsert_symbol_metadata(ticker, metadata)

    def _fetch_benchmark_from_api(
        self,
        ticker: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        full_history: bool = False,
    ) -> pd.DataFrame:
        try:
            resolved_end_date = end_date or datetime.now().strftime("%Y-%m-%d")
            from ta_core.database.models import MarketDataDaily

            if start_date is not None:
                resolved_start_date = start_date
            elif full_history:
                resolved_start_date = (datetime.now() - timedelta(days=3652)).strftime("%Y-%m-%d")
            else:
                last_record = (
                    self.repo.db.query(MarketDataDaily)
                    .filter(MarketDataDaily.ticker == ticker)
                    .order_by(MarketDataDaily.date.desc())
                    .first()
                )
                if last_record and last_record.date:
                    resolved_start_date = (last_record.date + timedelta(days=1)).strftime("%Y-%m-%d")
                else:
                    resolved_start_date = (datetime.now() - timedelta(days=3652)).strftime("%Y-%m-%d")

            if resolved_start_date > resolved_end_date:
                return pd.DataFrame()

            return self._fetch_quote_history(
                ticker,
                start_date=resolved_start_date,
                end_date=resolved_end_date,
                with_foreign_flow=False,
            )
        except Exception as exc:
            print(f"⚠️ Lỗi benchmark API nghiêm trọng khi tải {ticker}: {exc}")
            return pd.DataFrame()

    def sync_tickers(
        self,
        tickers: List[str],
        *,
        replace_existing: bool = False,
        max_requests_per_minute: int = 20,
        include_benchmarks: bool = True,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Dict[str, int]:
        """Sync selected tickers into the centralized data/vnstock.db."""
        results: Dict[str, int] = {}
        selected = [ticker.strip().upper() for ticker in tickers if ticker.strip()]
        if not selected and not include_benchmarks:
            return results

        total_items = (len(selected) * 2) + (len(self.benchmark_symbols) if include_benchmarks else 0)
        processed = 0

        for ticker in selected:
            processed += 1
            print(f"   [{processed}/{total_items}] Đang xử lý giá {ticker}...", end=" ")
            count = self._sync_symbol(
                ticker,
                replace_existing=replace_existing,
                with_foreign_flow=True,
                start_date=start_date,
                end_date=end_date,
            )
            if count > 0:
                if replace_existing:
                    print(f"✅ Đã thay thế {count} bản ghi.")
                else:
                    print(f"✅ Đã thêm {count} bản ghi.")
            else:
                from ta_core.database.models import MarketDataDaily
                last_record = self.repo.db.query(MarketDataDaily).filter(MarketDataDaily.ticker == ticker).order_by(MarketDataDaily.date.desc()).first()
                if last_record and last_record.date.strftime('%Y-%m-%d') >= (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d'):
                    print(f"✅ Dữ liệu đã cập nhật tới lịch sử gần nhất ({last_record.date.strftime('%Y-%m-%d')}).")
                else:
                    print("❌ Không tải được dữ liệu.")
            results[ticker] = count
            if processed < total_items:
                self._sleep_for_rpm(max_requests_per_minute)

            processed += 1
            print(f"   [{processed}/{total_items}] Đang xử lý ratios {ticker}...", end=" ")
            ratio_count = self._sync_financial_ratios(
                ticker,
                replace_existing=replace_existing,
            )
            if ratio_count > 0:
                if replace_existing:
                    print(f"✅ Đã thay thế {ratio_count} bản ghi quý.")
                else:
                    print(f"✅ Đã đồng bộ {ratio_count} bản ghi quý.")
            else:
                print("✅ Financial ratios đã mới nhất hoặc chưa có dữ liệu mới.")
            results[f"{ticker}_RATIOS"] = ratio_count
            self._sync_symbol_metadata(ticker)
            if processed < total_items:
                self._sleep_for_rpm(max_requests_per_minute)

        if include_benchmarks:
            for ticker in self.benchmark_symbols:
                processed += 1
                print(f"   [{processed}/{total_items}] Đang xử lý benchmark {ticker}...", end=" ")
                count = self._sync_symbol(
                    ticker,
                    replace_existing=replace_existing,
                    with_foreign_flow=False,
                    start_date=start_date,
                    end_date=end_date,
                )
                if count > 0:
                    if replace_existing:
                        print(f"✅ Đã thay thế {count} bản ghi.")
                    else:
                        print(f"✅ Đã thêm {count} bản ghi.")
                else:
                    print("✅ Benchmark đã mới nhất hoặc chưa có dữ liệu mới.")
                results[ticker] = count
                if processed < total_items:
                    self._sleep_for_rpm(max_requests_per_minute)
        return results

    def run_daily_update(self):
        """Hàm chính để chạy cập nhật hàng ngày"""
        print(f"\n🚀 BẮT ĐẦU CRAWL DATA & CẬP NHẬT DB ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
        print(f"📋 Danh sách theo dõi: {len(self.watchlist)} mã (VN30)")
        print("⏳ Đang tải dữ liệu 10 năm + financial ratios (có thể mất vài phút)...")

        try:
            results = self.sync_tickers(self.watchlist)
            total_new_records = sum(
                count for key, count in results.items() if not str(key).endswith("_RATIOS")
            )
            total_ratio_records = sum(
                count for key, count in results.items() if str(key).endswith("_RATIOS")
            )
            print("-" * 60)
            print(
                f"✅ HOÀN TẤT CẬP NHẬT. Giá mới: {total_new_records} bản ghi | "
                f"Ratios quý: {total_ratio_records} bản ghi."
            )
        finally:
            self.repo.close()

if __name__ == "__main__":
    # 1. Khởi tạo Database (Tạo bảng nếu chưa có)
    init_db()
    
    # 2. Chạy Crawler
    crawler = MarketCrawler()
    crawler.run_daily_update()