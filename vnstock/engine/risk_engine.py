from __future__ import annotations

from typing import Dict, List, Tuple

from config import risk_limits as default_risk_limits
from vnstock.database.repo import DataRepository
from vnstock.tools.backtest.portfolio import Portfolio

# Re-export RiskLimits from config for backward compatibility
RiskLimits = type(default_risk_limits)


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or default_risk_limits

    def check_buy_allowed(
        self,
        portfolio: Portfolio,
        ticker: str,
        price: float,
        price_map: Dict[str, float],
        target_weight_pct: float,
    ) -> Tuple[bool, str]:
        if price is None or price <= 0:
            return False, f"[risk] Invalid price for {ticker}"

        equity_now = portfolio.equity(price_map)
        if equity_now <= 0:
            return False, "[risk] Equity non-positive; blocking buys"

        current_notional = (portfolio.positions.get(ticker).total_qty * price) if portfolio.positions.get(ticker) else 0.0
        max_notional = equity_now * (self.limits.max_position_pct / 100.0)
        target_weight = min(target_weight_pct, self.limits.max_position_pct)
        target_notional = equity_now * (target_weight / 100.0)

        if current_notional >= max_notional - 1e-9:
            return False, f"[risk] {ticker} already at/above max position {self.limits.max_position_pct}%"

        incremental = max(0.0, target_notional - current_notional)
        projected_cash = portfolio.cash - min(portfolio.cash, incremental)
        min_cash = equity_now * (1 - self.limits.max_portfolio_invested_pct / 100.0)
        if projected_cash < min_cash - 1e-6:
            return False, f"[risk] Cash reserve < {100 - self.limits.max_portfolio_invested_pct:.1f}% if buying {ticker}"

        return True, ""

    def check_stop_loss(self, portfolio: Portfolio, price_map: Dict[str, float]) -> List[Dict[str, object]]:
        violations: List[Dict[str, object]] = []
        for ticker, pos in portfolio.positions.items():
            price = price_map.get(ticker)
            if price is None or price <= 0 or pos.avg_price <= 0:
                continue
            loss_pct = (pos.avg_price - price) / pos.avg_price * 100.0
            if loss_pct >= self.limits.stop_loss_pct and pos.settled_qty > 0:
                violations.append(
                    {
                        "ticker": ticker,
                        "loss_pct": round(loss_pct, 2),
                        "settled_qty": pos.settled_qty,
                    }
                )
        return violations

    def check_drawdown(
        self, equity_history: List[float], current_equity: float, start_capital: float
    ) -> Tuple[bool, float]:
        peak = max([start_capital] + list(equity_history) + [current_equity]) if start_capital is not None else max(
            list(equity_history) + [current_equity], default=0.0
        )
        if peak <= 0:
            return False, 0.0
        drawdown_pct = (peak - current_equity) / peak * 100.0
        return drawdown_pct >= self.limits.max_drawdown_pct, round(drawdown_pct, 2)

    def check_sector_exposure(
        self,
        portfolio: Portfolio,
        price_map: Dict[str, float],
        ticker: str,
        sector: str,
        target_weight_pct: float,
        repo: DataRepository | None = None,
    ) -> Tuple[bool, str]:
        """Check if adding this position would violate sector exposure limits.

        Args:
            repo: Optional DataRepository instance. If None, creates and closes one internally.
                  Pass existing repo to avoid resource leak when calling repeatedly.
        """
        if not sector or sector.lower() in ("other", "unknown", ""):
            return True, ""

        equity_now = portfolio.equity(price_map)
        if equity_now <= 0:
            return False, "[risk] Equity non-positive"

        # Calculate current exposure for the same sector only.
        sector_notional = 0.0
        should_close_repo = repo is None
        if repo is None:
            repo = DataRepository()
        try:
            for pos_ticker, pos in portfolio.positions.items():
                if pos_ticker == ticker:
                    continue  # target ticker handled separately via target_notional
                pos_sector = repo.resolve_sector_bucket(pos_ticker)
                if pos_sector != sector:
                    continue
                sector_notional += pos.total_qty * price_map.get(pos_ticker, 0.0)
        finally:
            if should_close_repo:
                repo.close()

        # Add target position
        price = price_map.get(ticker, 0.0)
        if price <= 0:
            return False, f"[risk] Invalid price for {ticker}"

        target_notional = equity_now * (target_weight_pct / 100.0)
        projected_sector_notional = sector_notional + target_notional
        projected_sector_pct = (projected_sector_notional / equity_now) * 100.0

        if projected_sector_pct > self.limits.max_sector_exposure_pct:
            return False, f"[risk] Sector {sector} would exceed {self.limits.max_sector_exposure_pct}% limit"

        return True, ""
