"""Deterministic confidence calibration backed by the cognitive calibration_store table."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.governance.schemas import AnalysisCard
from cognitive_trading.memory.calibration_store import CalibrationStore
from cognitive_trading.memory.db import CognitiveDB


@dataclass(slots=True)
class ConfidenceCalibrator:
    """Blend raw confidence with Bayesian-smoothed calibration history."""

    db_path: Path | str | None = None
    config: CognitiveConfig = CognitiveConfig()
    pseudo_count: int = 30
    raw_weight: float = 0.6
    historical_weight: float = 0.4
    cognitive_db: CognitiveDB | None = None

    def _store(self) -> CalibrationStore:
        return CalibrationStore(
            db_path=self.db_path,
            config=self.config,
            cognitive_db=self.cognitive_db,
        )

    def get_historical_win_rate(self, agent_name: str, sector: str) -> float:
        """Return win rate in 0..1, defaulting to 0.5 for unseen rows or missing DB."""

        return float(self._store().get_win_rate(agent_name, sector))

    def get_sample_count(self, agent_name: str, sector: str) -> int:
        """Return the number of matured calibration samples for one agent-sector pair."""

        return int(self._store().get_calibration(agent_name, sector)["total_calls"])

    def calibrate(self, *, raw_confidence: float, agent_name: str, sector: str) -> float:
        """Apply Bayesian smoothing plus weighted blending and return a 0..100 score."""

        sample_count = self.get_sample_count(agent_name, sector)
        historical_win_rate = self.get_historical_win_rate(agent_name, sector)
        prior_weight = max(0, int(self.pseudo_count))
        adjusted_win_rate = (
            (historical_win_rate * sample_count) + (0.5 * prior_weight)
        ) / (sample_count + prior_weight)
        calibrated = (float(raw_confidence) * self.raw_weight) + (
            adjusted_win_rate * 100.0 * self.historical_weight
        )
        return round(max(0.0, min(100.0, calibrated)), 4)

    def apply(self, card: AnalysisCard, sector: str) -> AnalysisCard:
        """Return a copy of the card with confidence_calibrated populated."""

        return card.model_copy(
            update={
                "confidence_calibrated": self.calibrate(
                    raw_confidence=card.confidence_raw,
                    agent_name=card.agent_name,
                    sector=sector,
                )
            }
        )


__all__ = ["ConfidenceCalibrator"]
