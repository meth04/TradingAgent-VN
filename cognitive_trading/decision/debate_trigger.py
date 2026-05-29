"""Conflict detection for deciding whether a cognitive_trading ticker needs debate."""

from __future__ import annotations

from typing import Sequence

from cognitive_trading.governance.schemas import AnalysisCard
from vnstock.agents.prompting import Action, normalize_action

BUY_FAMILY = {Action.BUY, Action.BUY_MORE}
SELL_FAMILY = {Action.SELL, Action.TRIMMING}
NEUTRAL_FAMILY = {Action.PASS}
LOW_AVERAGE_CONFIDENCE_THRESHOLD = 35.0
WIDE_CONFIDENCE_SPREAD_THRESHOLD = 50.0
MAGNITUDE_DISAGREEMENT_THRESHOLD = 40.0  # Upside/downside range > 40%


def action_direction(action: Action | str) -> str:
    """Return buy, sell, or neutral for a normalized action."""

    normalized = normalize_action(action)
    if normalized in BUY_FAMILY:
        return "buy"
    if normalized in SELL_FAMILY:
        return "sell"
    if normalized in NEUTRAL_FAMILY:
        return "neutral"
    raise ValueError(f"Unsupported action for debate trigger: {action}")


def _effective_confidence(card: AnalysisCard) -> float:
    confidence = (
        float(card.confidence_calibrated)
        if card.confidence_calibrated is not None
        else float(card.confidence_raw)
    )
    return max(0.0, min(100.0, confidence))


def _average_confidence(cards: Sequence[AnalysisCard]) -> float:
    if not cards:
        return 100.0
    return sum(_effective_confidence(card) for card in cards) / len(cards)


def _confidence_spread(cards: Sequence[AnalysisCard]) -> float:
    if not cards:
        return 0.0
    raw_confidences = [max(0.0, min(100.0, float(card.confidence_raw))) for card in cards]
    return max(raw_confidences) - min(raw_confidences)


def _magnitude_disagreement(cards: Sequence[AnalysisCard]) -> float:
    """Return range of upside/downside projections across agents."""
    if not cards:
        return 0.0
    upsides = [float(card.upside_pct) for card in cards]
    downsides = [float(card.downside_pct) for card in cards]
    upside_range = max(upsides) - min(upsides) if upsides else 0.0
    downside_range = max(downsides) - min(downsides) if downsides else 0.0
    return max(upside_range, downside_range)


def should_trigger_debate(cards: Sequence[AnalysisCard]) -> bool:
    """Return True on action conflict, low conviction, wide confidence dispersion, or magnitude disagreement."""

    if not cards:
        return False

    # 1. Direction conflict (BUY vs SELL)
    seen_buy = False
    seen_sell = False
    for card in cards:
        direction = action_direction(card.action)
        if direction == "buy":
            seen_buy = True
        elif direction == "sell":
            seen_sell = True
        if seen_buy and seen_sell:
            return True

    # 2. Low average confidence (high uncertainty)
    if _average_confidence(cards) < LOW_AVERAGE_CONFIDENCE_THRESHOLD:
        return True

    # 3. Wide confidence spread (disagreement in conviction)
    if _confidence_spread(cards) > WIDE_CONFIDENCE_SPREAD_THRESHOLD:
        return True

    # 4. Magnitude disagreement (large range in upside/downside projections)
    if _magnitude_disagreement(cards) > MAGNITUDE_DISAGREEMENT_THRESHOLD:
        return True

    return False


__all__ = ["action_direction", "should_trigger_debate"]
