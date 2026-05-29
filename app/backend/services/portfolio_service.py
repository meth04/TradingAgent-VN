"""Portfolio JSON persistence + real-time valuation."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from bootstrap import APP_DATA_DIR
from services.market_service import get_latest_prices

PORTFOLIO_PATH = APP_DATA_DIR / "portfolio.json"

DEFAULT_PORTFOLIO: Dict[str, Any] = {"cash": 0, "positions": []}


def load_portfolio() -> Dict[str, Any]:
    if not PORTFOLIO_PATH.exists():
        return dict(DEFAULT_PORTFOLIO)
    try:
        data = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_PORTFOLIO)
    return _normalize(data)


def save_portfolio(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize(data)
    PORTFOLIO_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return normalized


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    positions: List[Dict[str, Any]] = []
    for pos in (data or {}).get("positions") or []:
        ticker = str(pos.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        try:
            quantity = int(float(pos.get("quantity", 0)))
            avg_price = float(pos.get("avg_price", 0))
        except (TypeError, ValueError):
            continue
        if quantity <= 0:
            continue
        positions.append(
            {"ticker": ticker, "quantity": quantity, "avg_price": avg_price}
        )
    cash_raw = (data or {}).get("cash", 0)
    try:
        cash = float(cash_raw)
    except (TypeError, ValueError):
        cash = 0.0
    return {"cash": cash, "positions": positions}


def compute_value() -> Dict[str, Any]:
    portfolio = load_portfolio()
    positions = portfolio.get("positions") or []
    tickers = [p["ticker"] for p in positions]
    price_map = get_latest_prices(tickers)

    enriched: List[Dict[str, Any]] = []
    total_market_value_stocks = 0.0
    total_invested = 0.0
    for p in positions:
        current = float(price_map.get(p["ticker"], 0.0) or 0.0)
        market_value = current * p["quantity"]
        invested = p["avg_price"] * p["quantity"]
        pnl = market_value - invested
        pnl_pct = (pnl / invested * 100.0) if invested > 0 else 0.0
        enriched.append(
            {
                "ticker": p["ticker"],
                "quantity": p["quantity"],
                "avg_price": p["avg_price"],
                "current_price": round(current, 2),
                "market_value": round(market_value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
            }
        )
        total_market_value_stocks += market_value
        total_invested += invested

    cash = float(portfolio.get("cash", 0.0))
    total_market_value = total_market_value_stocks + cash
    total_pnl = total_market_value_stocks - total_invested
    base_capital = cash + total_invested  # what user effectively put in
    total_pnl_pct = (total_pnl / total_invested * 100.0) if total_invested > 0 else 0.0

    return {
        "cash": cash,
        "positions": enriched,
        "total_market_value": round(total_market_value, 2),
        "total_invested": round(total_invested, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "base_capital": round(base_capital, 2),
    }
