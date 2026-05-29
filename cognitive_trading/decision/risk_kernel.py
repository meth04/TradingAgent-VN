"""Deterministic risk validation and order approval for cognitive_trading."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.governance.schemas import IntentTicket, OrderTicket
from vnstock.agents.prompting import Action
from vnstock.database.repo import DataRepository
try:
    from vnstock.engine.risk_engine import RiskEngine, RiskLimits
except Exception:  # pragma: no cover - fallback when vnstock risk engine is broken
    @dataclass(frozen=True)
    class RiskLimits:  # type: ignore[no-redef]
        max_position_pct: float
        max_portfolio_invested_pct: float
        stop_loss_pct: float
        max_drawdown_pct: float

    class RiskEngine:  # type: ignore[no-redef]
        def __init__(self, limits: RiskLimits) -> None:
            self.limits = limits

        def check_drawdown(self, equity_history: list[float], equity_now: float, start_cash: float) -> tuple[bool, float]:
            history = [float(value) for value in equity_history if float(value) > 0.0]
            peak = max(history, default=float(start_cash))
            if peak <= 0:
                return False, 0.0
            drawdown_pct = max(0.0, (peak - float(equity_now)) / peak * 100.0)
            return drawdown_pct >= self.limits.max_drawdown_pct, round(drawdown_pct, 4)

        def check_stop_loss(self, portfolio: Portfolio, price_map: dict[str, float]) -> list[dict[str, Any]]:
            hits: list[dict[str, Any]] = []
            for ticker, position in portfolio.positions.items():
                price = float(price_map.get(ticker, 0.0) or 0.0)
                avg_price = float(position.avg_price or 0.0)
                settled_qty = float(position.settled_qty or 0.0)
                if price <= 0 or avg_price <= 0 or settled_qty <= 0:
                    continue
                pnl_pct = ((price - avg_price) / avg_price) * 100.0
                if pnl_pct <= -float(self.limits.stop_loss_pct):
                    hits.append({
                        'ticker': ticker,
                        'settled_qty': int(settled_qty),
                        'pnl_pct': round(pnl_pct, 4),
                    })
            return hits
from vnstock.tools.backtest.portfolio import BUY_FEE_RATE, LOT_SIZE, Portfolio, SELL_FEE_RATE


def infer_sector(ticker: str, repo: DataRepository | None = None) -> str:
    """Return a coarse sector bucket from symbol metadata for exposure tracking."""

    if repo is not None:
        return repo.resolve_sector_bucket(ticker)

    temp_repo = DataRepository()
    try:
        return temp_repo.resolve_sector_bucket(ticker)
    finally:
        temp_repo.close()


@dataclass(slots=True)
class RiskKernel:
    """Apply deterministic portfolio guardrails before trade execution."""

    config: CognitiveConfig = CognitiveConfig()
    repo: DataRepository | None = None
    max_sector_exposure_pct: float = 40.0
    risk_engine: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.risk_engine = RiskEngine(
            RiskLimits(
                max_position_pct=self.config.max_position_pct,
                max_portfolio_invested_pct=100.0 - self.config.min_cash_reserve_pct,
                stop_loss_pct=self.config.stop_loss_pct,
                max_drawdown_pct=self.config.max_drawdown_pct,
            )
        )

    def evaluate_intent(
        self,
        *,
        intent: IntentTicket,
        portfolio: Portfolio,
        price_map: Mapping[str, float],
        sector: str | None = None,
    ) -> OrderTicket | None:
        """Return an executable OrderTicket or None when no order is needed."""

        if intent.action == Action.PASS:
            return None

        ticker = intent.ticker.upper()
        price = float(price_map.get(ticker, 0.0) or 0.0)
        if price <= 0:
            return self._blocked_ticket(
                ticker=ticker,
                action=intent.action,
                price=price,
                reason="Missing or invalid VND price for current trading day.",
            )

        resolved_sector = sector or infer_sector(ticker, self.repo)
        equity_now = float(portfolio.equity(dict(price_map)))
        if equity_now <= 0:
            return self._blocked_ticket(
                ticker=ticker,
                action=intent.action,
                price=price,
                reason="Portfolio equity is non-positive.",
            )

        drawdown_halt, drawdown_pct = self.risk_engine.check_drawdown(
            portfolio.equity_history,
            equity_now,
            self.config.start_cash_vnd,
        )
        if drawdown_halt and intent.action in {Action.BUY, Action.BUY_MORE}:
            return self._blocked_ticket(
                ticker=ticker,
                action=intent.action,
                price=price,
                reason=(
                    f"Drawdown halt active at {drawdown_pct:.2f}% >= {self.config.max_drawdown_pct:.2f}%."
                ),
            )

        current_position = portfolio.positions.get(ticker)
        current_qty = float(current_position.total_qty) if current_position else 0.0
        current_settled_qty = float(current_position.settled_qty) if current_position else 0.0
        current_notional = current_qty * price
        target_weight_pct = round(max(0.0, min(self.config.max_position_pct, intent.weight_pct)), 4)
        target_notional = equity_now * (target_weight_pct / 100.0)

        if intent.action in {Action.BUY, Action.BUY_MORE}:
            return self._evaluate_buy(
                intent=intent,
                portfolio=portfolio,
                price_map=price_map,
                resolved_sector=resolved_sector,
                price=price,
                equity_now=equity_now,
                current_notional=current_notional,
                target_notional=target_notional,
            )

        return self._evaluate_sell(
            intent=intent,
            resolved_sector=resolved_sector,
            price_map=price_map,
            price=price,
            equity_now=equity_now,
            current_notional=current_notional,
            current_settled_qty=current_settled_qty,
            target_notional=target_notional,
        )

    def generate_stop_loss_orders(
        self,
        *,
        portfolio: Portfolio,
        price_map: Mapping[str, float],
    ) -> list[OrderTicket]:
        """Return approved stop-loss SELL orders for settled positions that breach the threshold."""

        hits = self.risk_engine.check_stop_loss(portfolio, dict(price_map))
        orders: list[OrderTicket] = []
        for hit in hits:
            ticker = str(hit["ticker"])
            qty = int(hit["settled_qty"])
            price = float(price_map.get(ticker, 0.0) or 0.0)
            if qty < LOT_SIZE or price <= 0:
                continue
            proceeds = qty * price * (1.0 - SELL_FEE_RATE)
            orders.append(
                OrderTicket(
                    ticker=ticker,
                    action=Action.SELL,
                    quantity=qty,
                    price=round(price, 4),
                    total_cost=round(proceeds, 4),
                    status="APPROVED",
                    block_reason=None,
                )
            )
        return orders

    def build_risk_report(
        self,
        *,
        portfolio: Portfolio,
        price_map: Mapping[str, float],
        blocked_orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return a JSON-serializable portfolio risk summary."""

        equity_now = float(portfolio.equity(dict(price_map)))
        drawdown_halt, drawdown_pct = self.risk_engine.check_drawdown(
            portfolio.equity_history,
            equity_now,
            self.config.start_cash_vnd,
        )
        sector_exposure_pct = self.sector_exposure_pct(portfolio=portfolio, price_map=price_map)
        stop_loss_hits = self.risk_engine.check_stop_loss(portfolio, dict(price_map))
        cash_pct = (portfolio.cash / equity_now * 100.0) if equity_now > 0 else 0.0
        return {
            "cash_vnd": round(float(portfolio.cash), 4),
            "equity_vnd": round(equity_now, 4),
            "cash_pct": round(float(cash_pct), 4),
            "sector_exposure_pct": sector_exposure_pct,
            "stop_loss_hits": stop_loss_hits,
            "drawdown_pct": round(float(drawdown_pct), 4),
            "drawdown_halt": bool(drawdown_halt),
            "blocked_orders": list(blocked_orders or []),
            "calibration_updates": [],
            "limits": {
                "max_position_pct": self.config.max_position_pct,
                "min_cash_reserve_pct": self.config.min_cash_reserve_pct,
                "stop_loss_pct": self.config.stop_loss_pct,
                "max_drawdown_pct": self.config.max_drawdown_pct,
                "max_sector_exposure_pct": self.max_sector_exposure_pct,
            },
        }

    def sector_exposure_pct(
        self,
        *,
        portfolio: Portfolio,
        price_map: Mapping[str, float],
    ) -> dict[str, float]:
        """Return current sector exposure as percent of portfolio equity."""

        equity_now = float(portfolio.equity(dict(price_map)))
        if equity_now <= 0:
            return {}

        exposures: dict[str, float] = {}
        for ticker, position in portfolio.positions.items():
            price = float(price_map.get(ticker, 0.0) or 0.0)
            if price <= 0:
                continue
            sector = infer_sector(ticker, self.repo)
            exposures[sector] = exposures.get(sector, 0.0) + (float(position.total_qty) * price)
        return {
            sector: round((notional / equity_now) * 100.0, 4)
            for sector, notional in sorted(exposures.items())
        }

    def should_trim_position(self, current_weight_pct: float) -> bool:
        """Return True if position weight exceeds max limit with 2% buffer to avoid whipsaw."""
        return current_weight_pct > (self.config.max_position_pct + 2.0)

    def enrich_portfolio_snapshot(
        self,
        *,
        portfolio: Portfolio,
        ticker: str,
        price_map: Mapping[str, float],
    ) -> dict[str, Any]:
        """Return a ticker-focused portfolio snapshot for CIO prompting."""

        snapshot = portfolio.snapshot(ticker, dict(price_map))
        price = float(price_map.get(ticker, 0.0) or 0.0)
        position = portfolio.positions.get(ticker)
        total_qty = float(position.total_qty) if position else 0.0
        settled_qty = float(position.settled_qty) if position else 0.0
        equity_now = float(snapshot.get("equity") or 0.0)
        current_weight_pct = ((total_qty * price) / equity_now * 100.0) if equity_now > 0 and price > 0 else 0.0
        snapshot["ticker"] = ticker.upper()
        snapshot["current_price_vnd"] = round(price, 4) if price > 0 else 0.0
        snapshot["current_weight_pct"] = round(float(current_weight_pct), 4)
        snapshot["available_for_sale_qty"] = int(settled_qty)  # T+2 rule: only settled shares can be sold
        snapshot["sector"] = infer_sector(ticker, self.repo)
        return snapshot

    def _evaluate_buy(
        self,
        *,
        intent: IntentTicket,
        portfolio: Portfolio,
        price_map: Mapping[str, float],
        resolved_sector: str,
        price: float,
        equity_now: float,
        current_notional: float,
        target_notional: float,
    ) -> OrderTicket:
        buy_allowed, reason = self.risk_engine.check_buy_allowed(
            portfolio,
            intent.ticker,
            price,
            dict(price_map),
            intent.weight_pct,
        )
        if not buy_allowed:
            return self._blocked_ticket(
                ticker=intent.ticker,
                action=intent.action,
                price=price,
                reason=reason,
            )

        incremental_notional = max(0.0, target_notional - current_notional)
        if incremental_notional <= 0.0:
            return self._blocked_ticket(
                ticker=intent.ticker,
                action=intent.action,
                price=price,
                reason="Target weight does not require additional shares.",
            )

        sector_exposure = self.sector_exposure_pct(portfolio=portfolio, price_map=price_map)
        projected_sector_exposure = sector_exposure.get(resolved_sector, 0.0) + (
            incremental_notional / equity_now * 100.0
        )

        # Warning for soft limit (30%)
        if projected_sector_exposure > 30.0:
            print(f"Warning: {resolved_sector} exposure at {projected_sector_exposure:.1f}%")

        if projected_sector_exposure > self.max_sector_exposure_pct:
            return self._blocked_ticket(
                ticker=intent.ticker,
                action=intent.action,
                price=price,
                reason=(
                    f"Sector exposure for {resolved_sector} would rise to "
                    f"{projected_sector_exposure:.2f}% > {self.max_sector_exposure_pct:.2f}%."
                ),
            )

        quantity = self._floor_lot(incremental_notional / (price * (1.0 + BUY_FEE_RATE)))
        if quantity < LOT_SIZE:
            return self._blocked_ticket(
                ticker=intent.ticker,
                action=intent.action,
                price=price,
                reason="Target weight is too small to buy one board lot after fees.",
            )

        total_cost = quantity * price * (1.0 + BUY_FEE_RATE)
        min_cash_vnd = equity_now * (self.config.min_cash_reserve_pct / 100.0)
        projected_cash = portfolio.cash - total_cost
        if projected_cash < min_cash_vnd - 1e-6:
            return self._blocked_ticket(
                ticker=intent.ticker,
                action=intent.action,
                price=price,
                reason=(
                    f"Projected cash reserve would fall below {self.config.min_cash_reserve_pct:.2f}% NAV."
                ),
            )

        return OrderTicket(
            ticker=intent.ticker,
            action=intent.action,
            quantity=quantity,
            price=round(price, 4),
            total_cost=round(total_cost, 4),
            status="APPROVED",
            block_reason=None,
        )

    def _evaluate_sell(
        self,
        *,
        intent: IntentTicket,
        resolved_sector: str,
        price_map: Mapping[str, float],
        price: float,
        equity_now: float,
        current_notional: float,
        current_settled_qty: float,
        target_notional: float,
    ) -> OrderTicket:
        del resolved_sector, price_map, equity_now
        if current_settled_qty < LOT_SIZE:
            return self._blocked_ticket(
                ticker=intent.ticker,
                action=intent.action,
                price=price,
                reason="No settled shares available under T+2.",
            )

        if intent.action == Action.SELL:
            quantity = self._floor_lot(current_settled_qty)
        else:
            sell_notional = max(0.0, current_notional - target_notional)
            quantity = self._floor_lot(sell_notional / price)
            quantity = min(quantity, self._floor_lot(current_settled_qty))

        if quantity < LOT_SIZE:
            return self._blocked_ticket(
                ticker=intent.ticker,
                action=intent.action,
                price=price,
                reason="Requested sell reduction is smaller than one settled board lot.",
            )

        proceeds = quantity * price * (1.0 - SELL_FEE_RATE)
        return OrderTicket(
            ticker=intent.ticker,
            action=intent.action,
            quantity=quantity,
            price=round(price, 4),
            total_cost=round(proceeds, 4),
            status="APPROVED",
            block_reason=None,
        )

    @staticmethod
    def _floor_lot(quantity: float) -> int:
        return int(math.floor(float(quantity) / LOT_SIZE) * LOT_SIZE)

    @staticmethod
    def _blocked_ticket(
        *,
        ticker: str,
        action: Action,
        price: float,
        reason: str,
    ) -> OrderTicket:
        return OrderTicket(
            ticker=ticker,
            action=action,
            quantity=0,
            price=round(max(0.0, float(price)), 4),
            total_cost=0.0,
            status="BLOCKED",
            block_reason=reason,
        )


__all__ = ["RiskKernel", "infer_sector"]
