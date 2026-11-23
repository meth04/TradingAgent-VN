"""Market-data facade over the ``vn-market-data`` package.

This is the only module in TradingAgent-VN that talks to Vietnamese market-data
providers. It replaces the old approach of running the ``vnstock`` library in a
subprocess, and converts vn-market-data's shapes into the ones ``data/vnstock.db``
already stores, so nothing downstream has to change:

- Stock prices are stored in **thousand VND** (the rest of the code multiplies by
  1000). vn-market-data returns full VND, so stock prices are divided by 1000.
  Index levels (VNINDEX, VN30) are points and are left as they are.
- Foreign flow is stored as share volumes in ``buy_foreign`` / ``sell_foreign``.

vn-market-data keeps its own SQLite cache. Its location comes from
``VN_MARKET_DATA_DB`` (see ``config.paths.market_data_cache_path``), so the cache
does not land in whatever folder the program happened to start in.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

INDEX_SYMBOLS = frozenset({"VNINDEX", "VN30", "HNXINDEX", "HNX30", "UPCOMINDEX", "VN100"})
PRICE_SCALE = 1000.0  # full VND -> thousand VND, the unit data/vnstock.db stores
PAR_VALUE_VND = 10_000.0  # every listed Vietnamese share has a 10,000 VND par value

_OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume", "buy_foreign", "sell_foreign"]


def _configure_cache_path() -> None:
    if os.getenv("VN_MARKET_DATA_DB"):
        return
    try:
        from config import paths

        cache_path = paths.market_data_cache_path
    except Exception:  # pragma: no cover - config unavailable (e.g. isolated tests)
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["VN_MARKET_DATA_DB"] = str(cache_path)


_configure_cache_path()

import vn_market_data as vmd  # noqa: E402  (must follow the cache-path setup)
from vn_market_data.adapter import get_foreign_archive, get_foreign_history  # noqa: E402  (not re-exported at top level)
from vn_market_data.sources.base import NotSupported, SourceUnavailable  # noqa: E402


def is_index(symbol: str) -> bool:
    return symbol.strip().upper() in INDEX_SYMBOLS


def _lookback_days(start_date: str) -> int:
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    return max((date.today() - start).days + 1, 1)


def get_daily_bars(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    with_foreign_flow: bool = True,
) -> pd.DataFrame:
    """Daily bars for ``[start_date, end_date]`` in the shape ``DataRepository`` saves.

    Returns an empty frame when no source answers and nothing is cached.
    """
    symbol = symbol.strip().upper()
    index = is_index(symbol)
    try:
        rows = vmd.get_ohlcv(symbol, lookback_days=_lookback_days(start_date), is_index=index)
    except (SourceUnavailable, NotSupported) as exc:
        log.warning("market data: no OHLCV for %s (%s)", symbol, exc)
        return pd.DataFrame(columns=_OHLCV_COLUMNS)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=_OHLCV_COLUMNS)

    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= pd.Timestamp(start_date)) & (df["date"] <= pd.Timestamp(end_date))].copy()
    for column in ("open", "high", "low", "close", "volume"):
        df[column] = pd.to_numeric(df.get(column), errors="coerce")
    if not index:
        for column in ("open", "high", "low", "close"):
            df[column] = df[column] / PRICE_SCALE
    df["volume"] = df["volume"].fillna(0)
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]

    df["buy_foreign"] = 0.0
    df["sell_foreign"] = 0.0
    if with_foreign_flow and not index and not df.empty:
        flow = get_foreign_flow(symbol, start_date, end_date)
        if not flow.empty:
            df = df.drop(columns=["buy_foreign", "sell_foreign"]).merge(flow, on="date", how="left")
            df[["buy_foreign", "sell_foreign"]] = df[["buy_foreign", "sell_foreign"]].fillna(0)

    return df[_OHLCV_COLUMNS].sort_values("date").reset_index(drop=True)


def get_foreign_flow(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Settled foreign buy/sell volumes per session: ``date, buy_foreign, sell_foreign``.

    Tries the settled source first (CafeF) and falls back to the multi-year archive
    (VNDirect). Sessions an archive reports as all-zero are dropped, as vn-market-data
    advises, because the archive can misread a whole session as zero.
    """
    empty = pd.DataFrame(columns=["date", "buy_foreign", "sell_foreign"])
    rows: list[dict] = []
    for fetch in (get_foreign_history, _foreign_archive):
        try:
            _, rows = fetch(symbol, start_date, end_date)
        except (SourceUnavailable, NotSupported) as exc:
            log.info("market data: foreign flow for %s unavailable from %s (%s)", symbol, fetch.__name__, exc)
            rows = []
        if rows:
            break
    if not rows:
        return empty

    df = pd.DataFrame(rows)
    if "date" not in df.columns:
        return empty
    df["date"] = pd.to_datetime(df["date"])
    df["buy_foreign"] = pd.to_numeric(df.get("buy_volume"), errors="coerce")
    df["sell_foreign"] = pd.to_numeric(df.get("sell_volume"), errors="coerce")
    df = df.dropna(subset=["buy_foreign", "sell_foreign"], how="all")
    return df[["date", "buy_foreign", "sell_foreign"]]


def _foreign_archive(symbol: str, start_date: str, end_date: str):
    source, rows = get_foreign_archive(symbol, start_date, end_date)
    rows = [
        r for r in rows
        if (r.get("buy_volume") or 0) != 0 or (r.get("sell_volume") or 0) != 0
    ]
    return source, rows


# ── Financial ratios ────────────────────────────────────────────────────────────

def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _growth_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous) * 100.0


def _previous_year_label(label: str) -> str:
    year, _, quarter = label.partition("-")
    return f"{int(year) - 1}-{quarter}" if quarter else str(int(year) - 1)


def _trailing_sum(series: dict[str, Any], label: str) -> float | None:
    """Sum of the four quarters ending at ``label`` (``YYYY-Qn``), or None if any is missing."""
    year, quarter = int(label[:4]), int(label[-1])
    total = 0.0
    for _ in range(4):
        value = series.get(f"{year}-Q{quarter}")
        if value is None:
            return None
        total += value
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return total


def _close_on_or_before(closes: pd.Series, label: str) -> float | None:
    """Close (full VND) on or before the quarter end named by ``label``."""
    year, quarter = int(label[:4]), int(label[-1])
    quarter_end = pd.Timestamp(year=year, month=quarter * 3, day=1) + pd.offsets.MonthEnd(0)
    eligible = closes[closes.index <= quarter_end]
    return float(eligible.iloc[-1]) if not eligible.empty else None


def get_quarterly_ratios(symbol: str) -> list[dict[str, Any]]:
    """Quarterly ratio records in the shape ``DataRepository.save_financial_ratios`` takes.

    vn-market-data returns raw statement line items only, so the ratios are computed
    here: ROE and ROA on trailing-twelve-month profit, EPS and book value per share
    from the share count implied by par-value capital, and P/E and P/B from the
    closing price at each quarter end. Beta is not available and is left empty.
    """
    symbol = symbol.strip().upper()
    try:
        payload = vmd.get_statement_history(symbol, "quarter")
    except (SourceUnavailable, NotSupported) as exc:
        log.warning("market data: no statements for %s (%s)", symbol, exc)
        return []
    if not payload:
        return []

    income = payload.get("statements", {}).get("income", {})
    balance = payload.get("statements", {}).get("balance", {})
    revenue = income.get("net_sales") or income.get("total_operating_income") or {}
    profit = income.get("net_profit_parent") or income.get("net_profit") or {}
    liabilities = balance.get("liabilities") or {}
    equity = balance.get("equity") or {}
    assets = balance.get("total_assets") or {}
    share_capital = balance.get("share_capital") or {}

    closes = pd.Series(dtype=float)
    try:
        bars = vmd.get_ohlcv(symbol, lookback_days=6 * 365)
        if bars:
            frame = pd.DataFrame(bars)
            closes = pd.Series(
                pd.to_numeric(frame["close"], errors="coerce").values,
                index=pd.to_datetime(frame["date"]),
            ).dropna().sort_index()
    except (SourceUnavailable, NotSupported):
        pass

    labels = sorted(
        (p for p in payload.get("periods", []) if len(p) == 7 and p[4:6] == "-Q"),
        key=lambda p: (int(p[:4]), int(p[-1])),
    )
    records: list[dict[str, Any]] = []
    for label in labels:
        shares = _ratio(share_capital.get(label), PAR_VALUE_VND)
        ttm_profit = _trailing_sum(profit, label)
        eps = _ratio(ttm_profit, shares)
        bvps = _ratio(equity.get(label), shares)
        close = _close_on_or_before(closes, label) if not closes.empty else None
        previous = _previous_year_label(label)
        records.append(
            {
                "ticker": symbol,
                "quarter": label,
                "trailing_eps": eps,
                "book_value_per_share": bvps,
                "pe": _ratio(close, eps) if eps and eps > 0 else None,
                "pb": _ratio(close, bvps) if bvps and bvps > 0 else None,
                "beta": None,
                "roe": _ratio(ttm_profit, equity.get(label)),
                "roa": _ratio(ttm_profit, assets.get(label)),
                "debt_equity": _ratio(liabilities.get(label), equity.get(label)),
                "net_revenue": revenue.get(label),
                "net_profit": profit.get(label),
                "revenue_yoy": _growth_pct(revenue.get(label), revenue.get(previous)),
                "net_profit_yoy": _growth_pct(profit.get(label), profit.get(previous)),
                "updated_at": datetime.now(),
            }
        )
    return records


# ── Company overview ────────────────────────────────────────────────────────────

_icb_cache: dict[int, dict[str, dict]] = {}


def _icb_sector(symbol: str, level: int) -> str | None:
    if level not in _icb_cache:
        try:
            _icb_cache[level] = vmd.VietcapSource().get_icb_sectors(level)
        except (SourceUnavailable, NotSupported) as exc:
            log.info("market data: ICB level %s unavailable (%s)", level, exc)
            return None
    entry = _icb_cache[level].get(symbol)
    return entry.get("sector") if entry else None


def get_company_overview(symbol: str) -> dict[str, Any]:
    """Company metadata in the shape ``DataRepository.upsert_symbol_metadata`` takes.

    Only keys with a value are returned, so a partial answer never blanks out
    metadata that is already stored.
    """
    symbol = symbol.strip().upper()
    overview: dict[str, Any] = {}
    try:
        company = vmd.VietcapSource().get_company(symbol) or {}
    except (SourceUnavailable, NotSupported) as exc:
        log.info("market data: company details for %s unavailable (%s)", symbol, exc)
        company = {}
    if company.get("name"):
        overview["company_name"] = company["name"]

    for level, key in ((2, "icb_name2"), (3, "icb_name3"), (4, "icb_name4")):
        sector = _icb_sector(symbol, level)
        if sector:
            overview[key] = sector
    if overview.get("icb_name2"):
        overview["industry"] = overview["icb_name2"]

    try:
        payload = vmd.get_statements(symbol, "quarter")
    except (SourceUnavailable, NotSupported):
        payload = None
    if payload and payload.get("periods"):
        latest = payload["periods"][0]
        capital = (payload.get("statements", {}).get("balance", {}).get("share_capital") or {}).get(latest)
        if capital:
            overview["charter_capital"] = int(capital)
            overview["outstanding_shares"] = int(capital / PAR_VALUE_VND)
    return overview
