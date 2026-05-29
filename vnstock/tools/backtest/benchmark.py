"""Benchmark comparison utilities for VNStock backtests."""

from __future__ import annotations

import math
from typing import Sequence


class BenchmarkAnalyzer:
    """Compare a strategy equity curve against a buy-and-hold benchmark."""

    def __init__(
        self,
        *,
        benchmark_name: str = "VN30",
        annual_trading_days: int = 252,
        risk_free_rate: float = 0.03,
    ) -> None:
        self.benchmark_name = benchmark_name
        self.annual_trading_days = annual_trading_days
        self.risk_free_rate = risk_free_rate

    def compare(
        self,
        equity_curve: Sequence[float],
        benchmark_prices: Sequence[float],
        start_capital: float,
    ) -> dict[str, float | int | str]:
        strategy_points = self._sanitize_series(equity_curve)
        benchmark_points = self._sanitize_series(benchmark_prices)
        count = min(len(strategy_points), len(benchmark_points))
        if count < 2:
            return self._empty_result(start_capital=start_capital)

        strategy_points = strategy_points[-count:]
        benchmark_points = benchmark_points[-count:]
        base_capital = float(start_capital) if start_capital > 0 else float(strategy_points[0])
        benchmark_curve = self._scale_benchmark(
            benchmark_points=benchmark_points,
            start_capital=base_capital,
        )
        strategy_daily = self._daily_returns(strategy_points)
        benchmark_daily = self._daily_returns(benchmark_curve)
        returns_count = min(len(strategy_daily), len(benchmark_daily))
        if returns_count == 0:
            return self._empty_result(start_capital=base_capital)

        strategy_daily = strategy_daily[-returns_count:]
        benchmark_daily = benchmark_daily[-returns_count:]
        mean_strategy = self._mean(strategy_daily)
        mean_benchmark = self._mean(benchmark_daily)
        benchmark_var = self._variance(benchmark_daily)
        beta = (
            self._covariance(strategy_daily, benchmark_daily) / benchmark_var
            if benchmark_var > 1e-12
            else 0.0
        )
        alpha_daily = mean_strategy - (beta * mean_benchmark)
        excess_returns = [
            strategy_ret - benchmark_ret
            for strategy_ret, benchmark_ret in zip(strategy_daily, benchmark_daily)
        ]
        tracking_error = math.sqrt(self._variance(excess_returns)) * math.sqrt(
            self.annual_trading_days
        )
        information_ratio = (
            (self._mean(excess_returns) * self.annual_trading_days) / tracking_error
            if tracking_error > 1e-12
            else 0.0
        )
        annual_strategy_return = mean_strategy * self.annual_trading_days
        treynor_ratio = (
            (annual_strategy_return - self.risk_free_rate) / beta
            if abs(beta) > 1e-12
            else 0.0
        )

        strategy_return_pct = self._total_return_pct(strategy_points)
        benchmark_return_pct = self._total_return_pct(benchmark_curve)
        return {
            "benchmark_name": self.benchmark_name,
            "strategy_return_pct": round(strategy_return_pct, 4),
            "benchmark_return_pct": round(benchmark_return_pct, 4),
            "active_return_pct": round(strategy_return_pct - benchmark_return_pct, 4),
            "alpha_annualized_pct": round(alpha_daily * self.annual_trading_days * 100.0, 4),
            "beta": round(beta, 6),
            "tracking_error_pct": round(tracking_error * 100.0, 4),
            "information_ratio": round(information_ratio, 6),
            "treynor_ratio": round(treynor_ratio, 6),
            "benchmark_final_value": round(float(benchmark_curve[-1]), 4),
            "benchmark_observations": returns_count,
        }

    @staticmethod
    def _sanitize_series(values: Sequence[float]) -> list[float]:
        return [float(value) for value in values if float(value) > 0.0]

    @staticmethod
    def _scale_benchmark(benchmark_points: Sequence[float], start_capital: float) -> list[float]:
        first_price = float(benchmark_points[0])
        if first_price <= 0:
            return [float(start_capital)]
        return [float(start_capital) * (float(price) / first_price) for price in benchmark_points]

    @staticmethod
    def _daily_returns(values: Sequence[float]) -> list[float]:
        returns: list[float] = []
        for previous, current in zip(values, values[1:]):
            if previous <= 0:
                continue
            returns.append((float(current) - float(previous)) / float(previous))
        return returns

    @staticmethod
    def _mean(values: Sequence[float]) -> float:
        if not values:
            return 0.0
        return sum(float(value) for value in values) / len(values)

    @classmethod
    def _variance(cls, values: Sequence[float]) -> float:
        if len(values) <= 1:
            return 0.0
        mean_value = cls._mean(values)
        return sum((float(value) - mean_value) ** 2 for value in values) / (len(values) - 1)

    @classmethod
    def _covariance(cls, left: Sequence[float], right: Sequence[float]) -> float:
        count = min(len(left), len(right))
        if count <= 1:
            return 0.0
        left_values = [float(value) for value in left[-count:]]
        right_values = [float(value) for value in right[-count:]]
        left_mean = cls._mean(left_values)
        right_mean = cls._mean(right_values)
        return sum(
            (left_value - left_mean) * (right_value - right_mean)
            for left_value, right_value in zip(left_values, right_values)
        ) / (count - 1)

    @staticmethod
    def _total_return_pct(values: Sequence[float]) -> float:
        if len(values) < 2 or float(values[0]) <= 0:
            return 0.0
        return ((float(values[-1]) - float(values[0])) / float(values[0])) * 100.0

    def _empty_result(self, *, start_capital: float) -> dict[str, float | int | str]:
        return {
            "benchmark_name": self.benchmark_name,
            "strategy_return_pct": 0.0,
            "benchmark_return_pct": 0.0,
            "active_return_pct": 0.0,
            "alpha_annualized_pct": 0.0,
            "beta": 0.0,
            "tracking_error_pct": 0.0,
            "information_ratio": 0.0,
            "treynor_ratio": 0.0,
            "benchmark_final_value": round(float(start_capital), 4),
            "benchmark_observations": 0,
        }


__all__ = ["BenchmarkAnalyzer"]
