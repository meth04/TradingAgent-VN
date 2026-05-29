from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import trading, strategy


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


START_CAPITAL = trading.portfolio_cash
LOT_SIZE = trading.lot_size
SETTLEMENT_LAG_DAYS = trading.settlement_lag_days
BUY_FEE_RATE = trading.buy_fee_rate
SELL_FEE_RATE = trading.sell_fee_rate
MAX_TRADE_PCT = trading.max_trade_pct
MAX_BUYS_PER_TICKER = trading.max_buys_per_ticker
QUAL_VERDICT_MAP = {
    "strong_bullish": 1.0,
    "bullish": 0.7,
    "neutral": 0.5,
    "bearish": 0.3,
    "strong_bearish": 0.0,
}


@dataclass
class StrategyParams:
    price_change_threshold: float = strategy.price_change_threshold
    vol_ratio_threshold: float = strategy.vol_ratio_threshold
    news_min_count: int = strategy.news_min_count
    news_lookback_days: int = strategy.news_lookback_days
    alpha_threshold: float = strategy.alpha_threshold
    sell_threshold_offset: float = strategy.sell_threshold_offset
    atr_scale: float = strategy.atr_scale
    weight_alpha: float = strategy.weight_alpha
    weight_beta: float = strategy.weight_beta


@dataclass
class TradeLot:
    qty: float
    price: float
    days_held: int = 0

    def __post_init__(self) -> None:
        if self.qty < 0:
            raise ValueError("Lot quantity cannot be negative")
        if self.price <= 0:
            raise ValueError("Lot price must be positive")
        if self.days_held < 0:
            raise ValueError("Lot days_held cannot be negative")
        if self.qty % LOT_SIZE != 0:
            raise ValueError("Lot quantity must align to lot size")


@dataclass
class Position:
    lots: List[TradeLot] = field(default_factory=list)

    @property
    def total_qty(self) -> float:
        return sum(lot.qty for lot in self.lots)

    @property
    def settled_qty(self) -> float:
        return sum(lot.qty for lot in self.lots if lot.days_held >= SETTLEMENT_LAG_DAYS)

    @property
    def avg_price(self) -> float:
        total_qty = self.total_qty
        if total_qty <= 0:
            return 0.0
        return sum(lot.qty * lot.price for lot in self.lots) / total_qty

    def add_lot(self, qty: float, price: float) -> None:
        self.lots.append(TradeLot(qty=qty, price=price, days_held=0))

    def increment_days(self) -> None:
        for lot in self.lots:
            lot.days_held += 1
        self._drop_empty()

    def consume_settled_fifo(self, qty: float) -> float:
        if qty <= 0:
            raise ValueError("Quantity must be positive")
        if qty % LOT_SIZE != 0:
            raise ValueError("Quantity must align to lot size")
        if qty > self.settled_qty:
            raise ValueError("Insufficient settled shares for T+2")

        remaining = qty
        new_lots: List[TradeLot] = []
        cost_basis = 0.0

        for lot in self.lots:
            if remaining <= 0:
                new_lots.append(lot)
                continue
            if lot.days_held < SETTLEMENT_LAG_DAYS:
                new_lots.append(lot)
                continue

            take_qty = min(lot.qty, remaining)
            # Include buy-side fee in cost basis to align with HOSE accounting
            cost_basis += take_qty * lot.price * (1 + BUY_FEE_RATE)
            leftover = lot.qty - take_qty
            if leftover > 0:
                new_lots.append(TradeLot(qty=leftover, price=lot.price, days_held=lot.days_held))
            remaining -= take_qty

            if remaining <= 0:
                continue

        if remaining > 0:
            # Defensive; should not happen due to settled_qty check
            raise ValueError("Insufficient settled shares for T+2")

        self.lots = new_lots
        self._drop_empty()
        return cost_basis

    def _drop_empty(self) -> None:
        self.lots = [lot for lot in self.lots if lot.qty > 0]


@dataclass
class Portfolio:
    cash: float = START_CAPITAL
    positions: Dict[str, Position] = field(default_factory=dict)
    trades: int = 0
    sells: int = 0
    wins: int = 0
    equity_history: List[float] = field(default_factory=list)
    last_date: Optional[str] = None
    buys_per_ticker: Dict[str, int] = field(default_factory=dict)

    def equity(self, price_lookup: Dict[str, float]) -> float:
        total = self.cash
        for ticker, pos in self.positions.items():
            price = price_lookup.get(ticker)
            if price is None or price <= 0:
                continue
            total += pos.total_qty * price
        return total

    def rollover_day(self, current_date: Optional[str] = None) -> None:
        if self.last_date and current_date is not None and current_date <= self.last_date:
            print(
                f"[portfolio.rollover_day] Warning: non-increasing date encountered: {current_date} after {self.last_date}"
            )

        to_remove: List[str] = []
        for ticker, pos in self.positions.items():
            pos.increment_days()
            if pos.total_qty <= 0:
                to_remove.append(ticker)
        for ticker in to_remove:
            self.positions.pop(ticker, None)

        # Reset daily buy counter to avoid permanent blocks across days
        self.buys_per_ticker.clear()

        if current_date is not None:
            self.last_date = current_date

    def buy(self, ticker: str, price: float, invest: float) -> tuple[bool, float]:
        if invest <= 0 or price <= 0:
            return False, 0.0

        # Enforce per-trade sizing cap
        pct = MAX_TRADE_PCT if MAX_TRADE_PCT <= 1.0 else (MAX_TRADE_PCT / 100.0)
        max_invest = self.cash * pct
        capped_invest = min(invest, max_invest)

        # Enforce max buys per ticker
        if self.buys_per_ticker.get(ticker, 0) >= MAX_BUYS_PER_TICKER:
            print(f"[portfolio.buy] Max buys reached for {ticker}")
            return False, 0.0

        affordable_qty = math.floor((capped_invest / (price * (1 + BUY_FEE_RATE))) / LOT_SIZE) * LOT_SIZE
        if affordable_qty < LOT_SIZE:
            print(f"[portfolio.buy] Insufficient invest to purchase one lot for {ticker}")
            return False, 0.0

        cost = affordable_qty * price * (1 + BUY_FEE_RATE)
        if cost - self.cash > 1e-9:
            print(f"[portfolio.buy] Not enough cash to buy {affordable_qty} of {ticker}: cost={cost}, cash={self.cash}")
            return False, cost

        pos = self.positions.get(ticker, Position())
        pos.add_lot(affordable_qty, price)
        self.positions[ticker] = pos
        self.cash -= cost
        self.trades += 1
        self.buys_per_ticker[ticker] = self.buys_per_ticker.get(ticker, 0) + 1
        return True, cost

    def sell(self, ticker: str, qty: Optional[float], price: float) -> float:
        if price <= 0:
            raise ValueError("Price must be positive")
        if qty is None:
            raise ValueError("Quantity must be provided")
        if qty <= 0:
            raise ValueError("Quantity must be positive")
        if qty % LOT_SIZE != 0:
            raise ValueError("Quantity must align to lot size")

        pos = self.positions.get(ticker)
        if not pos:
            raise ValueError("Insufficient settled shares for T+2")

        cost_basis = pos.consume_settled_fifo(qty)
        proceeds = qty * price * (1 - SELL_FEE_RATE)
        pnl = proceeds - cost_basis
        if pnl > 0:
            self.wins += 1

        if pos.total_qty <= 0:
            self.positions.pop(ticker, None)
            # Clear daily buy counter when position fully exits to avoid residual blocks
            self.buys_per_ticker.pop(ticker, None)
        else:
            self.positions[ticker] = pos

        self.cash += proceeds
        self.trades += 1
        self.sells += 1
        return pnl

    def sell_all_settled(self, ticker: str, price: float) -> float:
        pos = self.positions.get(ticker)
        settled_qty = pos.settled_qty if pos else 0.0
        if settled_qty <= 0:
            raise ValueError("0 settled shares to sell")
        return self.sell(ticker, settled_qty, price)

    def sell_fraction_settled(self, ticker: str, price: float, fraction) -> float:
        pos = self.positions.get(ticker)
        settled_qty = pos.settled_qty if pos else 0.0
        frac_val = self._parse_fraction(fraction)
        qty = math.floor((settled_qty * frac_val) / LOT_SIZE) * LOT_SIZE
        if qty < LOT_SIZE:
            raise ValueError("Insufficient settled shares for T+2")
        return self.sell(ticker, qty, price)

    @staticmethod
    def _parse_fraction(fraction) -> float:
        if isinstance(fraction, str):
            fraction = fraction.strip()
            if fraction.endswith("%"):
                fraction = fraction[:-1]
            try:
                fraction = float(fraction)
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError("Invalid fraction format") from exc
        if isinstance(fraction, (int, float)):
            frac_val = float(fraction)
        else:
            raise ValueError("Invalid fraction format")

        if frac_val > 1:
            frac_val = frac_val / 100.0
        frac_val = max(0.0, min(1.0, frac_val))
        return frac_val

    def snapshot(self, ticker: str, price_lookup: Dict[str, float]) -> Dict[str, object]:
        equity_now = self.equity(price_lookup)
        positions_view: Dict[str, object] = {}
        for tk, pos in self.positions.items():
            positions_view[tk] = {
                "lots": [
                    {"qty": lot.qty, "price": lot.price, "days_held": lot.days_held}
                    for lot in pos.lots
                ],
                "total_qty": pos.total_qty,
                "settled_qty": pos.settled_qty,
                "avg_price": pos.avg_price,
            }

        pos = self.positions.get(ticker)
        price = price_lookup.get(ticker)
        unrealized = 0.0
        unrealized_pnl_pct = 0.0
        if pos and price is not None and price > 0:
            unrealized = pos.total_qty * (price - pos.avg_price)
            if pos.avg_price > 0:
                unrealized_pnl_pct = ((price - pos.avg_price) / pos.avg_price) * 100.0

        return {
            "cash": self.cash,
            "equity": equity_now,
            "positions": positions_view,
            "unrealized_pnl": unrealized,
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
            "last_date": self.last_date,
        }

    def save_state(self, path: Path) -> None:
        payload = {
            "cash": self.cash,
            "positions": {
                ticker: {
                    "lots": [
                        {"qty": lot.qty, "price": lot.price, "days_held": lot.days_held}
                        for lot in pos.lots
                    ],
                }
                for ticker, pos in self.positions.items()
            },
            "trades": self.trades,
            "sells": self.sells,
            "wins": self.wins,
            "equity_history": self.equity_history,
            "last_date": self.last_date,
            "buys_per_ticker": self.buys_per_ticker,
        }
        _ensure_dir(path)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)

    @classmethod
    def load_state(cls, path: Path, *, allow_reset: bool = False) -> "Portfolio":
        if not path.exists():
            return cls()

        raw = path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except Exception as exc:
            backup_path = _backup_corrupted(path, raw)
            if allow_reset:
                print(f"[portfolio.load_state] Resetting portfolio due to parse error; backup at {backup_path}")
                return cls()
            raise ValueError(f"Failed to parse portfolio state: {exc}") from exc

        try:
            positions = cls._parse_positions(data.get("positions"))
        except Exception:
            backup_path = _backup_corrupted(path, raw)
            if allow_reset:
                print(f"[portfolio.load_state] Resetting portfolio due to invalid positions; backup at {backup_path}")
                return cls()
            raise

        portfolio = cls()
        portfolio.cash = float(data.get("cash", START_CAPITAL))
        portfolio.trades = int(data.get("trades", 0))
        portfolio.sells = int(data.get("sells", 0))
        portfolio.wins = int(data.get("wins", 0))
        portfolio.equity_history = list(data.get("equity_history", []))
        portfolio.last_date = data.get("last_date")
        portfolio.positions = positions
        buys_per_ticker = data.get("buys_per_ticker", {})
        if isinstance(buys_per_ticker, dict):
            portfolio.buys_per_ticker = {str(k): int(v) for k, v in buys_per_ticker.items()}
        else:
            portfolio.buys_per_ticker = {}
        return portfolio

    @staticmethod
    def _parse_positions(positions_data) -> Dict[str, Position]:
        if positions_data is None:
            return {}
        if not isinstance(positions_data, dict):
            raise ValueError("Positions payload invalid")

        positions: Dict[str, Position] = {}
        for ticker, pos_data in positions_data.items():
            if not isinstance(pos_data, dict):
                raise ValueError(f"Position for {ticker} must be a dict")
            lots_data = pos_data.get("lots")
            if not isinstance(lots_data, list):
                raise ValueError(f"Position {ticker} missing lots list")

            lots: List[TradeLot] = []
            for lot_data in lots_data:
                if not isinstance(lot_data, dict):
                    raise ValueError(f"Lot entry for {ticker} must be a dict")
                qty = lot_data.get("qty")
                price = lot_data.get("price")
                days_held = lot_data.get("days_held", 0)
                lot = TradeLot(qty=float(qty), price=float(price), days_held=int(days_held))
                lots.append(lot)

            positions[ticker] = Position(lots=lots)
        return positions


def _backup_corrupted(path: Path, raw: str) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    backup_path = path.with_name(f"{path.stem}_corrupted_{ts}{path.suffix}")
    _ensure_dir(backup_path)
    backup_path.write_text(raw, encoding="utf-8")
    return backup_path
