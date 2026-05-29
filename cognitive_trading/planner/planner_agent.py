"""Plan-and-Solve router for deciding which analyst set to run per ticker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from config import strategy as shared_strategy

NORMAL_ANALYSTS = ("technical", "quant")
HIGH_IMPACT_ANALYSTS = ("macro", "technical", "quant", "news", "financial")


@dataclass(frozen=True, slots=True)
class PlannerDecision:
    """Deterministic routing decision for a ticker."""

    ticker: str
    classification: str
    analysts: tuple[str, ...]
    reasons: tuple[str, ...]
    thresholds: dict[str, float | int]
    metrics: dict[str, float | int | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "classification": self.classification,
            "analysts": list(self.analysts),
            "reasons": list(self.reasons),
            "thresholds": self.thresholds,
            "metrics": self.metrics,
        }


@dataclass(slots=True)
class PlannerAgent:
    """Classify a ticker as normal or high_impact without LLM calls."""

    price_change_threshold: float = shared_strategy.price_change_threshold
    volume_ratio_threshold: float = shared_strategy.vol_ratio_threshold
    news_count_threshold: int = shared_strategy.news_min_count

    def classify(self, *, ticker: str, context: Mapping[str, Any]) -> PlannerDecision:
        """Route the ticker using deterministic planner thresholds."""

        price_context = context.get("price_context", {})
        news_context = context.get("news_context", {})
        volume_context = price_context.get("volume_context", {})

        recent_price_change_pct = self._as_float(price_context.get("recent_price_change_pct"))
        volume_ratio = self._as_float(volume_context.get("ratio_to_20d"))
        news_count = self._as_int(news_context.get("count"))

        reasons: list[str] = []
        if recent_price_change_pct is not None and abs(recent_price_change_pct) > self.price_change_threshold:
            reasons.append(
                f"price_change>{self.price_change_threshold} ({recent_price_change_pct:.4f})"
            )
        if volume_ratio is not None and volume_ratio > self.volume_ratio_threshold:
            reasons.append(f"volume_ratio>{self.volume_ratio_threshold} ({volume_ratio:.4f})")
        if news_count > self.news_count_threshold:
            reasons.append(f"news_count>{self.news_count_threshold} ({news_count})")

        classification = "high_impact" if reasons else "normal"
        analysts = HIGH_IMPACT_ANALYSTS if classification == "high_impact" else NORMAL_ANALYSTS

        return PlannerDecision(
            ticker=ticker,
            classification=classification,
            analysts=analysts,
            reasons=tuple(reasons) or ("thresholds_not_triggered",),
            thresholds={
                "price_change_threshold": self.price_change_threshold,
                "volume_ratio_threshold": self.volume_ratio_threshold,
                "news_count_threshold": self.news_count_threshold,
            },
            metrics={
                "recent_price_change_pct": recent_price_change_pct,
                "volume_ratio": volume_ratio,
                "news_count": news_count,
            },
        )

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _as_int(value: Any) -> int:
        if value is None:
            return 0
        return int(value)


__all__ = [
    "HIGH_IMPACT_ANALYSTS",
    "NORMAL_ANALYSTS",
    "PlannerAgent",
    "PlannerDecision",
]
