"""Offline tests for the vn-market-data facade and the crawler that uses it.

A fake source replaces the real providers, so these run without network access.
Run with:  python -m pytest tests -q
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

QUARTERS = ["2026-Q3", "2026-Q2", "2026-Q1", "2025-Q4", "2025-Q3", "2025-Q2", "2025-Q1", "2024-Q4"]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("VNSTOCK_DB_PATH", str(tmp_path / "vnstock.db"))
    monkeypatch.setenv("VN_MARKET_DATA_DB", str(tmp_path / "vmd.db"))

    import vn_market_data as vmd
    from vn_market_data.sources.base import DataSource

    days = [d for d in (date.today() - timedelta(days=i) for i in range(60, -1, -1)) if d.weekday() < 5]

    class FakeSource(DataSource):
        name = "fake"

        def get_ohlcv(self, symbol, start, end, *, is_index=False):
            price = 1250.0 if is_index else 95_000.0
            return [
                {"date": d.isoformat(), "open": price, "high": price, "low": price, "close": price, "volume": 1e6}
                for d in days if start <= d.isoformat() <= end
            ]

        def get_foreign_history(self, symbol, start, end):
            return [
                {"date": d.isoformat(), "buy_volume": 1000, "sell_volume": 400}
                for d in days if start <= d.isoformat() <= end
            ]

        def get_statements(self, symbol, period="year"):
            same = lambda v: {q: v for q in QUARTERS}  # noqa: E731
            return {
                "kind": "general",
                "periods": QUARTERS,
                "statements": {
                    "income": {"net_sales": same(1e12), "net_profit_parent": same(2e11)},
                    "balance": {
                        "liabilities": same(5e12),
                        "equity": same(4e12),
                        "total_assets": same(9e12),
                        "share_capital": same(1e12),
                    },
                    "cashflow": {},
                },
                "ratio_extra": {},
                "ratio_labels": "source",
            }

    vmd.set_sources([FakeSource()])
    from ta_core.data import market_data

    class FakeVietcap:
        def get_company(self, symbol):
            return {"name": "FPT Corp", "sector": "Technology"}

        def get_icb_sectors(self, level):
            return {"FPT": {"sector": f"ICB{level}"}}

    monkeypatch.setattr(market_data.vmd, "VietcapSource", FakeVietcap)
    market_data._icb_cache.clear()
    yield market_data, tmp_path
    vmd.set_sources(vmd.build_sources())


def test_stock_prices_are_stored_in_thousand_vnd_with_foreign_flow(env):
    market_data, _ = env
    start = (date.today() - timedelta(days=30)).isoformat()
    df = market_data.get_daily_bars("FPT", start, date.today().isoformat())
    assert not df.empty
    assert df["close"].iloc[-1] == pytest.approx(95.0)
    assert df["buy_foreign"].iloc[-1] == 1000
    assert df["sell_foreign"].iloc[-1] == 400


def test_index_levels_are_not_scaled(env):
    market_data, _ = env
    start = (date.today() - timedelta(days=30)).isoformat()
    df = market_data.get_daily_bars("VNINDEX", start, date.today().isoformat(), with_foreign_flow=False)
    assert df["close"].iloc[-1] == pytest.approx(1250.0)


def test_quarterly_ratios(env):
    market_data, _ = env
    latest = market_data.get_quarterly_ratios("FPT")[-1]
    assert latest["quarter"] == "2026-Q3"
    assert latest["trailing_eps"] == pytest.approx(8000.0)      # 4 x 200bn / 100m shares
    assert latest["book_value_per_share"] == pytest.approx(40000.0)
    assert latest["roe"] == pytest.approx(0.2)
    assert latest["debt_equity"] == pytest.approx(1.25)


def test_crawler_sync_is_incremental(env):
    _, tmp_path = env
    from ta_core.database.models import init_db
    from ta_core.jobs.crawler import MarketCrawler

    init_db()
    crawler = MarketCrawler()
    crawler.benchmark_symbols = ["VNINDEX"]
    first = crawler.sync_tickers(["FPT"], max_requests_per_minute=0)
    second = crawler.sync_tickers(["FPT"], max_requests_per_minute=0)
    assert first["FPT"] > 0 and first["VNINDEX"] > 0 and first["FPT_RATIOS"] == len(QUARTERS)
    assert second["FPT"] == 0 and second["VNINDEX"] == 0

    db = sqlite3.connect(tmp_path / "vnstock.db")
    name = db.execute("select company_name, icb_name2 from symbols where ticker='FPT'").fetchone()
    assert name == ("FPT Corp", "ICB2")
