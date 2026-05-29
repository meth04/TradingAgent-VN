"""Promote and demote cognitive_trading playbooks from episodic memory patterns."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.memory.db import CognitiveDB, init_memory_db


@dataclass(slots=True)
class PromotionEngine:
    """Create, freeze, and demote strategy playbooks based on episodic alpha patterns."""

    db_path: Path | str | None = None
    config: CognitiveConfig = CognitiveConfig()
    cognitive_db: CognitiveDB | None = None

    def scan_for_patterns(self) -> list[dict[str, Any]]:
        """Return promotable sector+macro clusters from profitable relative-performance episodes."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                  lower(coalesce(sector, 'other')) AS sector,
                  coalesce(trim(macro_summary), '') AS macro_summary,
                  COUNT(*) AS sample_count,
                  AVG(alpha_vs_vn30) AS avg_alpha,
                  MAX(action) AS recommended_action
                FROM episodic_memory
                WHERE alpha_vs_vn30 IS NOT NULL
                  AND alpha_vs_vn30 > 0
                  AND coalesce(trim(macro_summary), '') != ''
                GROUP BY lower(coalesce(sector, 'other')), coalesce(trim(macro_summary), '')
                HAVING COUNT(*) >= 3 AND AVG(alpha_vs_vn30) > 1.0
                ORDER BY AVG(alpha_vs_vn30) DESC, COUNT(*) DESC
                """
            ).fetchall()

        candidates: list[dict[str, Any]] = []
        for row in rows:
            payload = dict(row)
            sector = str(payload.get("sector") or "other")
            macro_summary = str(payload.get("macro_summary") or "").strip()
            avg_alpha = round(float(payload.get("avg_alpha") or 0.0), 4)
            sample_count = int(payload.get("sample_count") or 0)
            candidates.append(
                {
                    "name": f"{sector}_{sample_count}_{abs(int(avg_alpha * 100))}",
                    "pattern_description": f"Sector={sector}; macro_summary={macro_summary}",
                    "target_sectors": [sector],
                    "recommended_action": self._recommended_action_for_pattern(sector=sector, macro_summary=macro_summary),
                    "avg_alpha": avg_alpha,
                    "sample_count": sample_count,
                    "invalidation_condition": f"Freeze after 3 consecutive negative-alpha matches for sector={sector} and macro_summary={macro_summary}",
                }
            )
        return candidates

    def promote(self, *, candidate: Mapping[str, Any]) -> dict[str, Any]:
        """Insert a new active playbook and persist a human-readable JSON artifact."""

        payload = {
            "name": str(candidate.get("name") or "playbook").strip(),
            "pattern_description": str(candidate.get("pattern_description") or "").strip(),
            "target_sectors": list(candidate.get("target_sectors") or []),
            "recommended_action": str(candidate.get("recommended_action") or "HOLD").strip().upper(),
            "avg_alpha": round(float(candidate.get("avg_alpha") or 0.0), 4),
            "sample_count": int(candidate.get("sample_count") or 0),
            "status": "active",
            "invalidation_condition": str(candidate.get("invalidation_condition") or "").strip() or None,
        }
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO strategy_memory (
                  name,
                  pattern_description,
                  target_sectors,
                  recommended_action,
                  avg_alpha,
                  sample_count,
                  status,
                  invalidation_condition,
                  created_at,
                  last_used,
                  consecutive_losses
                )
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?, datetime('now'), NULL, 0)
                """,
                (
                    payload["name"],
                    payload["pattern_description"],
                    json.dumps(payload["target_sectors"], ensure_ascii=False),
                    payload["recommended_action"],
                    payload["avg_alpha"],
                    payload["sample_count"],
                    payload["invalidation_condition"],
                ),
            )
            connection.commit()
            playbook_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM strategy_memory WHERE id = ?",
                (playbook_id,),
            ).fetchone()

        playbook = self._deserialize_playbook(row)
        self._write_playbook_file(playbook)
        return playbook

    def demote(self) -> list[dict[str, Any]]:
        """Freeze or demote playbooks whose last three matches all had negative alpha."""

        updated: list[dict[str, Any]] = []
        for playbook in self.get_active_playbooks(statuses=("active", "frozen")):
            recent_matches = self._recent_matches(playbook=playbook, limit=3)
            if len(recent_matches) < 3:
                continue
            if not all(float(item.get("alpha_vs_vn30") or 0.0) < 0.0 for item in recent_matches):
                continue

            consecutive_losses = int(playbook.get("consecutive_losses") or 0) + 1
            status = "demoted" if consecutive_losses >= 5 else "frozen"
            with self._connection() as connection:
                connection.execute(
                    """
                    UPDATE strategy_memory
                    SET status = ?, consecutive_losses = ?
                    WHERE id = ?
                    """,
                    (status, consecutive_losses, int(playbook["id"])),
                )
                connection.commit()
                row = connection.execute(
                    "SELECT * FROM strategy_memory WHERE id = ?",
                    (int(playbook["id"]),),
                ).fetchone()
            refreshed = self._deserialize_playbook(row)
            self._write_playbook_file(refreshed)
            updated.append(refreshed)
        return updated

    def get_active_playbooks(self, *, statuses: tuple[str, ...] = ("active",)) -> list[dict[str, Any]]:
        """Return active or optionally frozen playbooks for CIO fast-path lookup."""

        placeholders = ", ".join("?" for _ in statuses)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM strategy_memory WHERE status IN ({placeholders}) ORDER BY avg_alpha DESC, id ASC",
                tuple(statuses),
            ).fetchall()
        return [self._deserialize_playbook(row) for row in rows]

    def match_playbook(
        self,
        *,
        ticker: str,
        sector: str,
        macro_context: Mapping[str, Any] | str | None,
    ) -> dict[str, Any] | None:
        """Return the first active playbook whose sector and macro pattern match the current context."""

        del ticker
        macro_text = self._macro_text(macro_context).lower()
        normalized_sector = sector.strip().lower()
        for playbook in self.get_active_playbooks():
            target_sectors = [str(item).strip().lower() for item in playbook.get("target_sectors", [])]
            if target_sectors and normalized_sector not in target_sectors:
                continue
            pattern_description = str(playbook.get("pattern_description") or "").lower()
            macro_pattern = self._extract_macro_pattern(pattern_description)
            if macro_pattern and macro_pattern not in macro_text:
                continue
            return playbook
        return None

    def _recent_matches(self, *, playbook: Mapping[str, Any], limit: int) -> list[dict[str, Any]]:
        sector = self._primary_sector(playbook)
        macro_pattern = self._extract_macro_pattern(str(playbook.get("pattern_description") or ""))
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM episodic_memory
                WHERE lower(coalesce(sector, 'other')) = ?
                  AND lower(coalesce(macro_summary, '')) LIKE ?
                  AND alpha_vs_vn30 IS NOT NULL
                ORDER BY trade_date DESC, id DESC
                LIMIT ?
                """,
                (sector, f"%{macro_pattern.lower()}%", max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _recommended_action_for_pattern(*, sector: str, macro_summary: str) -> str:
        text = f"{sector} {macro_summary}".lower()
        negative_tokens = ("risk", "tighten", "sell", "bear", "downgrade", "stress")
        return "SELL" if any(token in text for token in negative_tokens) else "BUY"

    @staticmethod
    def _extract_macro_pattern(pattern_description: str) -> str:
        marker = "macro_summary="
        lowered = pattern_description.lower()
        index = lowered.find(marker)
        if index == -1:
            return ""
        return pattern_description[index + len(marker):].strip().lower()

    @staticmethod
    def _macro_text(macro_context: Mapping[str, Any] | str | None) -> str:
        if isinstance(macro_context, str):
            return macro_context
        if not isinstance(macro_context, Mapping):
            return ""
        parts = []
        summary = macro_context.get("summary")
        if summary:
            parts.append(str(summary))
        for article in macro_context.get("top_articles", []) or []:
            if isinstance(article, Mapping) and article.get("title"):
                parts.append(str(article["title"]))
        return " | ".join(parts)

    @staticmethod
    def _primary_sector(playbook: Mapping[str, Any]) -> str:
        sectors = playbook.get("target_sectors") or []
        if isinstance(sectors, list) and sectors:
            return str(sectors[0]).strip().lower()
        return "other"

    def _write_playbook_file(self, playbook: Mapping[str, Any]) -> None:
        path = self.config.playbooks_dir / f"{int(playbook['id'])}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(playbook, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def _deserialize_playbook(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {}
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


__all__ = ["PromotionEngine"]
