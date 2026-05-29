import io
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import requests

from vnstock.database.models import init_db
from vnstock.database.repo import DataRepository

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

    def _fetch_foreign_history_scrape(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Attempt to scrape historical foreign flow from Vietstock as fallback."""
        try:
            url = (
                "https://finance.vietstock.vn/data/stockforeign"
                f"?symbol={ticker}&fromDate={start_date}&toDate={end_date}"
                "&sortBy=tradingDate&sortDir=asc&pageSize=5000&page=1"
            )
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://finance.vietstock.vn/",
            }
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                return pd.DataFrame()
            data = resp.json()
            items = data.get("data", []) if isinstance(data, dict) else []
            if not items:
                return pd.DataFrame()
            df = pd.DataFrame(items)
            for col in df.columns:
                if col.lower() == "tradingdate":
                    df.rename(columns={col: "date"}, inplace=True)
                if col.lower() == "buyvolume":
                    df.rename(columns={col: "buy_foreign"}, inplace=True)
                if col.lower() == "sellvolume":
                    df.rename(columns={col: "sell_foreign"}, inplace=True)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
            for c in ["buy_foreign", "sell_foreign"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
            return df[[c for c in df.columns if c in ["date", "buy_foreign", "sell_foreign"]]]
        except Exception:
            return pd.DataFrame()

    def _merge_foreign_snapshot(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """Merge current-day KBS price_board foreign volumes into df if available."""
        try:
            from vnstock.explorer.kbs.trading import Trading

            board = Trading().price_board([ticker], get_all=True)
            if board.empty:
                return df
            row = board.iloc[0]
            fb = row.get("foreign_buy_volume", 0)
            fs = row.get("foreign_sell_volume", 0)
            if df.empty or "date" not in df.columns:
                return df
            latest_date = df["date"].max()
            df.loc[df["date"] == latest_date, "buy_foreign"] = fb
            df.loc[df["date"] == latest_date, "sell_foreign"] = fs
            return df
        except Exception:
            return df

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Chuẩn hóa tên cột về định dạng thống nhất cho Database"""
        # 1. Đưa hết về chữ thường
        df.columns = [str(c).lower().strip() for c in df.columns]
        
        # 2. Map tên cột từ các nguồn khác nhau về chuẩn chung
        rename_map = {
            'time': 'date',
            'tradingdate': 'date',
            'datetime': 'date',
            'date_time': 'date',
            'vol': 'volume',
            'volume': 'volume',
            'nm_volume': 'volume', # Khớp lệnh
            'high': 'high',
            'low': 'low',
            'open': 'open',
            'close': 'close',
            'buy_foreign_quantity': 'buy_foreign',
            'sell_foreign_quantity': 'sell_foreign',
            'foreign_buy': 'buy_foreign',
            'foreign_sell': 'sell_foreign',
            'buyvalueforeign': 'buy_foreign',
            'sellvalueforeign': 'sell_foreign',
            'fmv': 'buy_foreign',
            'fms': 'sell_foreign',
            'buy_foreign_value': 'buy_foreign',
            'sell_foreign_value': 'sell_foreign',
            'foreign_buy_volume': 'buy_foreign',
            'foreign_sell_volume': 'sell_foreign'
        }
        
        df = df.rename(columns=rename_map)
        
        # 3. Đảm bảo các cột bắt buộc phải có (nếu thiếu thì fill 0)
        required_cols = ['buy_foreign', 'sell_foreign', 'volume']
        for col in required_cols:
            if col not in df.columns:
                df[col] = 0
                
        return df

    def _fetch_from_api(
        self,
        ticker: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        full_history: bool = False,
    ) -> pd.DataFrame:
        """Gọi API Vnstock lấy dữ liệu + foreign flow cho window yêu cầu hoặc toàn bộ lịch sử."""
        try:
            resolved_end_date = end_date or datetime.now().strftime("%Y-%m-%d")

            from vnstock.database.models import MarketDataDaily

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

    def _base_external_vnstock_script(
        self,
        *,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[str]:
        script_lines = [
            "import os",
            "import site",
            "import sys",
            f"ticker = {ticker!r}",
            f"start_date = {start_date!r}",
            f"end_date = {end_date!r}",
            f"project_root = {str(Path(__file__).resolve().parents[2])!r}",
            "filtered = []",
            "for path in sys.path:",
            "    resolved = os.path.abspath(path or '.')",
            "    if resolved == project_root or resolved.startswith(os.path.join(project_root, 'vnstock')):",
            "        continue",
            "    filtered.append(path)",
            "for package_dir in site.getsitepackages():",
            "    if package_dir not in filtered:",
            "        filtered.insert(0, package_dir)",
            "sys.path = filtered",
        ]
        return script_lines

    @staticmethod
    def _extract_json_array(output: str) -> str:
        start = output.find("[")
        end = output.rfind("]")
        if start == -1 or end == -1 or end < start:
            return ""
        return output[start : end + 1]

    def _fetch_quote_history(
        self,
        ticker: str,
        *,
        start_date: str,
        end_date: str,
        with_foreign_flow: bool,
    ) -> pd.DataFrame:
        try:
            script_lines = self._base_external_vnstock_script(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
            )
            if with_foreign_flow:
                script_lines.extend(
                    [
                        "from vnstock import Vnstock",
                        "df = Vnstock().stock(symbol=ticker, source='KBS').quote.history(start=start_date, end=end_date, interval='1D', get_all=True)",
                    ]
                )
            else:
                script_lines.extend(
                    [
                        "from vnstock import Quote",
                        "df = Quote(symbol=ticker, source='VCI').history(start=start_date, end=end_date, interval='1D')",
                    ]
                )
            script_lines.extend(
                [
                    "if df is None or df.empty:",
                    "    print('[]')",
                    "else:",
                    "    print(df.to_json(orient='records', date_format='iso'))",
                ]
            )
            res = subprocess.run([sys.executable, "-c", "\n".join(script_lines)], capture_output=True, text=True)
            out = self._extract_json_array(res.stdout.strip())
            if not out:
                return pd.DataFrame()
            df = pd.read_json(io.StringIO(out), orient="records")
            if df is None or df.empty:
                return pd.DataFrame()

            df = self._normalize_columns(df)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
            numeric_cols = ["open", "high", "low", "close", "volume", "buy_foreign", "sell_foreign"]
            for column in numeric_cols:
                if column in df.columns:
                    df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
            df = df.dropna(subset=["date"])
            df = df[df["close"] > 0]

            if with_foreign_flow:
                foreign_df = self._fetch_foreign_history_scrape(
                    ticker,
                    start_date,
                    end_date,
                )
                if not foreign_df.empty:
                    df = df.merge(foreign_df, on="date", how="left", suffixes=("", "_scrape"))
                    if "buy_foreign_scrape" in df.columns:
                        df["buy_foreign"] = df["buy_foreign_scrape"].fillna(df["buy_foreign"])
                        df.drop(columns=["buy_foreign_scrape"], inplace=True)
                    if "sell_foreign_scrape" in df.columns:
                        df["sell_foreign"] = df["sell_foreign_scrape"].fillna(df["sell_foreign"])
                        df.drop(columns=["sell_foreign_scrape"], inplace=True)
                df = self._merge_foreign_snapshot(df, ticker)

            return df
        except Exception:
            return pd.DataFrame()

    @staticmethod
    def _quarter_sort_key(quarter: str) -> tuple[int, int]:
        try:
            year_str, quarter_str = quarter.split("-Q", maxsplit=1)
            return int(year_str), int(quarter_str)
        except (AttributeError, TypeError, ValueError):
            return (0, 0)

    def _ratio_record_from_rows(
        self,
        *,
        ticker: str,
        quarter: str,
        rows: dict[str, dict[str, Any]],
        previous_rows: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        previous_rows = previous_rows or {}
        quarter_key = quarter.lower()
        current_revenue = self.repo._to_ratio_value(rows.get("net_revenue", {}).get(quarter_key))
        previous_revenue = self.repo._to_ratio_value(previous_rows.get("net_revenue", {}).get(quarter_key))
        current_profit = self.repo._to_ratio_value(
            rows.get("profit_after_tax_for_shareholders_of_the_parent_company", {}).get(quarter_key)
        )
        previous_profit = self.repo._to_ratio_value(
            previous_rows.get("profit_after_tax_for_shareholders_of_the_parent_company", {}).get(quarter_key)
        )
        liabilities = self.repo._to_ratio_value(rows.get("liabilities", {}).get(quarter_key))
        owners_equity = self.repo._to_ratio_value(rows.get("owners_equity", {}).get(quarter_key))
        debt_equity = None
        if liabilities is not None and owners_equity not in (None, 0):
            debt_equity = liabilities / owners_equity

        return {
            "ticker": ticker,
            "quarter": quarter,
            "trailing_eps": self.repo._to_ratio_value(rows.get("trailing_eps", {}).get(quarter_key)),
            "book_value_per_share": self.repo._to_ratio_value(
                rows.get("book_value_per_share_bvps", {}).get(quarter_key)
            ),
            "pe": self.repo._to_ratio_value(rows.get("p_e", {}).get(quarter_key)),
            "pb": self.repo._to_ratio_value(rows.get("p_b", {}).get(quarter_key)),
            "beta": self.repo._to_ratio_value(rows.get("beta", {}).get(quarter_key)),
            "roe": self.repo._to_ratio_value(rows.get("roe", {}).get(quarter_key)),
            "roa": self.repo._to_ratio_value(rows.get("roa", {}).get(quarter_key)),
            "debt_equity": debt_equity,
            "net_revenue": current_revenue,
            "net_profit": current_profit,
            "revenue_yoy": self.repo._growth_pct(current_revenue, previous_revenue),
            "net_profit_yoy": self.repo._growth_pct(current_profit, previous_profit),
            "updated_at": datetime.now(),
        }

    def _fetch_financial_ratios(self, ticker: str) -> list[dict[str, Any]]:
        try:
            script_lines = self._base_external_vnstock_script(ticker=ticker)
            script_lines.extend(
                [
                    "from vnstock import Finance",
                    "df = Finance(symbol=ticker, source='KBS').ratio(period='quarter')",
                    "if df is None or df.empty:",
                    "    print('[]')",
                    "else:",
                    "    print(df.to_json(orient='records'))",
                ]
            )
            res = subprocess.run([sys.executable, "-c", "\n".join(script_lines)], capture_output=True, text=True)
            out = self._extract_json_array(res.stdout.strip())
            if not out:
                return []
            df = pd.read_json(io.StringIO(out), orient="records")
            if df is None or df.empty or "item_id" not in df.columns:
                return []

            df.columns = [str(col).strip().lower() for col in df.columns]
            quarter_columns = [
                col for col in df.columns if isinstance(col, str) and len(col) == 7 and col[4:6] == "-q"
            ]
            if not quarter_columns:
                quarter_columns = [
                    col
                    for col in df.columns
                    if isinstance(col, str) and col.count("-") == 1 and col.lower().startswith(("202", "201"))
                ]
            normalized_df = df.copy()
            normalized_df["item_id"] = normalized_df["item_id"].astype(str).str.strip().str.lower()
            rows = {
                str(row["item_id"]): row.to_dict()
                for _, row in normalized_df.iterrows()
                if str(row.get("item_id", "")).strip()
            }
            quarter_names = sorted({str(col).upper() for col in quarter_columns}, key=self._quarter_sort_key)
            records: list[dict[str, Any]] = []
            for quarter in quarter_names:
                previous_year_key = f"{int(quarter[:4]) - 1}-Q{quarter[-1]}"
                record = self._ratio_record_from_rows(
                    ticker=ticker,
                    quarter=quarter,
                    rows=rows,
                    previous_rows=rows,
                )
                record["revenue_yoy"] = self.repo._growth_pct(
                    record["net_revenue"],
                    self.repo._to_ratio_value(rows.get("net_revenue", {}).get(previous_year_key.lower())),
                )
                record["net_profit_yoy"] = self.repo._growth_pct(
                    record["net_profit"],
                    self.repo._to_ratio_value(
                        rows.get("profit_after_tax_for_shareholders_of_the_parent_company", {}).get(previous_year_key.lower())
                    ),
                )
                records.append(record)
            return records
        except Exception:
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
            script_lines = self._base_external_vnstock_script(ticker=ticker)
            script_lines.extend(
                [
                    "from vnstock import Company",
                    "df = Company(symbol=ticker, source='VCI').overview()",
                    "if df is None or df.empty:",
                    "    print('{}')",
                    "else:",
                    "    print(df.iloc[0].to_json())",
                ]
            )
            res = subprocess.run([sys.executable, "-c", "\n".join(script_lines)], capture_output=True, text=True)
            out = res.stdout.strip()
            start = out.find("{")
            end = out.rfind("}")
            if start == -1 or end == -1 or end < start:
                return {}
            payload = pd.read_json(io.StringIO(f"[{out[start:end + 1]}]"), orient="records")
            if payload.empty:
                return {}
            row = payload.iloc[0].to_dict()
            return {
                "ticker": ticker,
                "company_name": row.get("company_profile"),
                "exchange": "HOSE",
                "industry": row.get("icb_name2"),
                "icb_name2": row.get("icb_name2"),
                "icb_name3": row.get("icb_name3"),
                "icb_name4": row.get("icb_name4"),
                "charter_capital": int(float(row["charter_capital"])) if row.get("charter_capital") not in (None, "") else None,
                "outstanding_shares": int(float(row["issue_share"])) if row.get("issue_share") not in (None, "") else None,
            }
        except Exception:
            return {}

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
            from vnstock.database.models import MarketDataDaily

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
                from vnstock.database.models import MarketDataDaily
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