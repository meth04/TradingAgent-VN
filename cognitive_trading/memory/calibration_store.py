"""Win-rate tracking for cognitive_trading analyst calibration."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.memory.db import CognitiveDB, init_memory_db
from vnstock.agents.prompting import Action, normalize_action

_BUY_ACTIONS = {Action.BUY, Action.BUY_MORE}
_SELL_ACTIONS = {Action.SELL, Action.TRIMMING}
_NEUTRAL_ACTIONS = {Action.PASS}


@dataclass(slots=True)
class CalibrationStore:
    """CRUD helpers for calibration_store with deterministic correctness rules."""

    db_path: Path | str | None = None
    config: CognitiveConfig = CognitiveConfig()
    cognitive_db: CognitiveDB | None = None

    def get_calibration(self, agent_name: str, sector: str) -> dict[str, Any]:
        """Return one calibration row with safe defaults for unseen agent-sector pairs."""

        normalized_agent = agent_name.strip().lower()
        normalized_sector = sector.strip().lower()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT agent_name, sector, total_calls, correct_calls, win_rate, last_updated
                FROM calibration_store
                WHERE agent_name = ? AND sector = ?
                """,
                (normalized_agent, normalized_sector),
            ).fetchone()
        if row is None:
            return {
                "agent_name": normalized_agent,
                "sector": normalized_sector,
                "total_calls": 0,
                "correct_calls": 0,
                "win_rate": 0.5,
                "last_updated": None,
            }
        payload = dict(row)
        payload["total_calls"] = int(payload.get("total_calls") or 0)
        payload["correct_calls"] = int(payload.get("correct_calls") or 0)
        payload["win_rate"] = max(0.0, min(1.0, float(payload.get("win_rate") or 0.5)))
        return payload

    def get_win_rate(self, agent_name: str, sector: str) -> float:
        """Return stored win rate in 0..1, defaulting to 0.5."""

        return float(self.get_calibration(agent_name, sector)["win_rate"])

    def record_outcome(self, *, agent_name: str, sector: str, was_correct: bool) -> dict[str, Any]:
        """Upsert one agent-sector calibration row after a matured outcome."""

        normalized_agent = agent_name.strip().lower()
        normalized_sector = sector.strip().lower()
        increment = 1 if was_correct else 0
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO calibration_store (
                  agent_name,
                  sector,
                  total_calls,
                  correct_calls,
                  win_rate,
                  last_updated
                ) VALUES (?, ?, 1, ?, ?, datetime('now'))
                ON CONFLICT(agent_name, sector) DO UPDATE SET
                  total_calls = calibration_store.total_calls + 1,
                  correct_calls = calibration_store.correct_calls + excluded.correct_calls,
                  win_rate = CAST(calibration_store.correct_calls + excluded.correct_calls AS REAL)
                    / CAST(calibration_store.total_calls + 1 AS REAL),
                  last_updated = datetime('now')
                """,
                (
                    normalized_agent,
                    normalized_sector,
                    increment,
                    float(increment),
                ),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT agent_name, sector, total_calls, correct_calls, win_rate, last_updated
                FROM calibration_store
                WHERE agent_name = ? AND sector = ?
                """,
                (normalized_agent, normalized_sector),
            ).fetchone()
        return dict(row) if row is not None else {}

    def get_all_calibrations(self) -> list[dict[str, Any]]:
        """Return all calibration rows for reporting."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT agent_name, sector, total_calls, correct_calls, win_rate, last_updated
                FROM calibration_store
                ORDER BY agent_name ASC, sector ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    @classmethod
    def evaluate_prediction_correctness(
        cls,
        *,
        action: str | Action,
        pnl_t5: float | int | None,
    ) -> bool:
        """Return whether an action was correct under the project t+5 rules."""

        normalized_action = normalize_action(action)
        if normalized_action is None or pnl_t5 is None:
            return False

        pnl_value = float(pnl_t5)
        if normalized_action in _BUY_ACTIONS:
            return pnl_value > 0.0
        if normalized_action in _SELL_ACTIONS:
            return pnl_value < 0.0
        if normalized_action in _NEUTRAL_ACTIONS:
            return abs(pnl_value) < 3.0
        return False

    def record_from_episode(
        self,
        *,
        episode: Mapping[str, Any],
        agent_cards: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluate each agent independently using directional correctness."""

        sector = str(episode.get("sector") or "other").strip().lower() or "other"
        pnl_t5 = episode.get("pnl_t5")

        # Use directional correctness: did agent's action match price movement?
        # This evaluates each agent independently, not against episode outcome
        records: list[dict[str, Any]] = []
        for card in agent_cards or []:
            agent_name = str(card.get("agent_name") or card.get("agent") or "").strip().lower()
            if not agent_name:
                continue
            card_action = card.get("action") or "PASS"

            # Independent evaluation: agent is correct if their directional call matched price movement
            card_correct = self.evaluate_prediction_correctness(
                action=card_action,
                pnl_t5=pnl_t5,
            )
            records.append(
                self.record_outcome(
                    agent_name=agent_name,
                    sector=sector,
                    was_correct=card_correct,
                )
            )
        return records

    def _resolved_db_path(self) -> Path:
        if self.cognitive_db is not None:
            return self.cognitive_db.path
        target = self.db_path if self.db_path is not None else self.config.memory_db_path
        return init_memory_db(target)

    def _connection(self) -> sqlite3.Connection:
        if self.cognitive_db is not None:
            return self.cognitive_db.connection()
        connection = sqlite3.connect(self._resolved_db_path())
        connection.row_factory = sqlite3.Row
        return connection


__all__ = ["CalibrationStore"]
