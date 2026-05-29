"""CRUD helpers for cognitive_trading strategy_memory playbooks."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.memory.db import CognitiveDB, init_memory_db


@dataclass(slots=True)
class StrategyStore:
    """Read and update playbooks stored in the cognitive strategy_memory table."""

    db_path: Path | str | None = None
    config: CognitiveConfig = CognitiveConfig()
    cognitive_db: CognitiveDB | None = None

    def get_playbook(self, playbook_id: int | str) -> dict[str, Any] | None:
        """Return one playbook by id."""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM strategy_memory WHERE id = ?",
                (int(playbook_id),),
            ).fetchone()
        return self._deserialize_playbook(row)

    def list_active(self) -> list[dict[str, Any]]:
        """Return all active playbooks ordered by avg_alpha descending."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM strategy_memory
                WHERE status = 'active'
                ORDER BY avg_alpha DESC, id ASC
                """
            ).fetchall()
        return [self._deserialize_playbook(row) for row in rows if row is not None]

    def list_all(self) -> list[dict[str, Any]]:
        """Return all playbooks for artifact export."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM strategy_memory
                ORDER BY status ASC, avg_alpha DESC, id ASC
                """
            ).fetchall()
        return [self._deserialize_playbook(row) for row in rows if row is not None]

    def update_last_used(self, playbook_id: int | str) -> bool:
        """Stamp a playbook with the current SQLite timestamp."""

        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE strategy_memory SET last_used = datetime('now') WHERE id = ?",
                (int(playbook_id),),
            )
            connection.commit()
        return cursor.rowcount > 0

    def freeze(self, playbook_id: int | str) -> bool:
        """Mark a playbook as frozen."""

        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE strategy_memory SET status = 'frozen' WHERE id = ?",
                (int(playbook_id),),
            )
            connection.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _deserialize_playbook(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        payload = dict(row)
        target_sectors = payload.get("target_sectors")
        if isinstance(target_sectors, str) and target_sectors.strip():
            try:
                payload["target_sectors"] = json.loads(target_sectors)
            except json.JSONDecodeError:
                payload["target_sectors"] = [target_sectors]
        elif target_sectors is None:
            payload["target_sectors"] = []
        return payload

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


__all__ = ["StrategyStore"]
