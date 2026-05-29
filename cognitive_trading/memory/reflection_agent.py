"""Outcome attribution and learning summary generation for cognitive_trading."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.memory.db import CognitiveDB, init_memory_db
from cognitive_trading.memory.calibration_store import CalibrationStore
from cognitive_trading.memory.episodic_store import EpisodicStore
from vnstock.core.llm import LLMError, call_llm
from vnstock.database.repo import DataRepository
from vnstock.tools.backtest.trading_calendar import iter_trading_days


def _normalize_date(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _trading_days_elapsed(start_date: str, end_date: str) -> int:
    start_ts = _normalize_date(start_date)
    end_ts = _normalize_date(end_date)
    if end_ts <= start_ts:
        return 0
    return sum(1 for _ in iter_trading_days((start_ts + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), end_ts.strftime("%Y-%m-%d")))


@dataclass(slots=True)
class ReflectionAgent:
    """Evaluate matured episodes, update calibration, and write a reflection summary."""

    db_path: Path | str | None = None
    config: CognitiveConfig = CognitiveConfig()
    repo: DataRepository | None = None
    episodic_store: EpisodicStore | None = None
    calibration_store: CalibrationStore | None = None
    cognitive_db: CognitiveDB | None = None
    _owns_repo: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.repo is None:
            self.repo = DataRepository()
            self._owns_repo = True
        if self.episodic_store is None:
            self.episodic_store = EpisodicStore(
                db_path=self.db_path,
                config=self.config,
                repo=self.repo,
                cognitive_db=self.cognitive_db,
            )
        if self.calibration_store is None:
            self.calibration_store = CalibrationStore(
                db_path=self.db_path,
                config=self.config,
                cognitive_db=self.cognitive_db,
            )

    def close(self) -> None:
        """Release the shared repository if this agent created it."""

        if self._owns_repo and self.repo is not None:
            self.repo.close()
            self.repo = None

    def find_matured_episodes(self, *, last_backtest_date: str) -> list[dict[str, Any]]:
        """Return episodes that are old enough for t+5 evaluation but not yet scored."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM episodic_memory
                WHERE pnl_t5 IS NULL
                  AND trade_date < ?
                ORDER BY trade_date ASC, id ASC
                """,
                (last_backtest_date,),
            ).fetchall()
        matured: list[dict[str, Any]] = []
        for row in rows:
            episode = self._deserialize_episode(row)
            if _trading_days_elapsed(str(episode["trade_date"]), last_backtest_date) >= 5:
                matured.append(episode)
        return matured

    def evaluate(self, *, last_backtest_date: str) -> list[dict[str, Any]]:
        """Update matured episodes with t+1/t+3/t+5 and optional t+20 outcomes."""

        updated_episodes: list[dict[str, Any]] = []
        for episode in self.find_matured_episodes(last_backtest_date=last_backtest_date):
            episode_id = int(episode["id"])
            latest = episode
            for horizon in (1, 3, 5):
                refreshed = self.episodic_store.update_outcome(episode_id=episode_id, horizon_days=horizon)
                if refreshed is not None:
                    latest = refreshed
            if _trading_days_elapsed(str(episode["trade_date"]), last_backtest_date) >= 20:
                refreshed = self.episodic_store.update_outcome(episode_id=episode_id, horizon_days=20)
                if refreshed is not None:
                    latest = refreshed
            latest = self.episodic_store.get_episode(episode_id) or latest
            if latest.get("pnl_t5") is not None:
                updated_episodes.append(latest)
        return updated_episodes

    def attribute(self, *, episodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Update calibration rows for all analysts that contributed to the matured episodes."""

        calibration_updates: list[dict[str, Any]] = []
        for episode in episodes:
            cards = self._agent_cards_from_episode(episode)
            if not cards or episode.get("pnl_t5") is None:
                continue
            calibration_updates.extend(
                self.calibration_store.record_from_episode(
                    episode=episode,
                    agent_cards=cards,
                )
            )
        return calibration_updates

    async def generate_reflection_summary(
        self,
        *,
        last_backtest_date: str,
        episodes: Sequence[Mapping[str, Any]] | None = None,
    ) -> str:
        """Write a brief reflection report summarizing learned agent and sector performance."""

        payload = self._summary_payload(last_backtest_date=last_backtest_date, episodes=episodes)
        try:
            report = await call_llm(
                system_prompt=(
                    "Bạn viết báo cáo học hỏi Markdown ngắn gọn cho cognitive_trading. "
                    "Chỉ dùng JSON đã cung cấp. Không tự bịa thành tích hay nhận định hiệu suất."
                ),
                user_prompt=(
                    "Hãy viết báo cáo Markdown với đúng thứ tự các mục sau:\n"
                    "# Tóm tắt phản tư Cognitive Trading\n"
                    "## Độ chính xác của agent\n"
                    "## Bài học theo ngành\n"
                    "## Các episode đã trưởng thành gần đây\n"
                    "Dùng gạch đầu dòng ngắn và trích số liệu trực tiếp từ JSON.\n\n"
                    f"DATA:\n{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}"
                ),
                model=self.config.reflection_model,
                temperature=0.1,
                
            )
        except LLMError:
            report = self._fallback_summary(payload)

        output_path = self.config.output_root / "reflection_summary.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        return report

    def _summary_payload(
        self,
        *,
        last_backtest_date: str,
        episodes: Sequence[Mapping[str, Any]] | None,
    ) -> dict[str, Any]:
        recent_episodes = [dict(item) for item in (episodes or self._recent_evaluated_episodes(limit=20))]
        sector_rollup: dict[str, dict[str, float | int]] = {}
        for episode in recent_episodes:
            sector = str(episode.get("sector") or "other").strip().lower() or "other"
            bucket = sector_rollup.setdefault(
                sector,
                {"sample_count": 0, "avg_pnl_t5": 0.0, "avg_alpha": 0.0},
            )
            bucket["sample_count"] = int(bucket["sample_count"]) + 1
            bucket["avg_pnl_t5"] = float(bucket["avg_pnl_t5"]) + float(episode.get("pnl_t5") or 0.0)
            bucket["avg_alpha"] = float(bucket["avg_alpha"]) + float(episode.get("alpha_vs_vn30") or 0.0)

        sector_summary = []
        for sector, stats in sorted(sector_rollup.items()):
            count = int(stats["sample_count"])
            if count <= 0:
                continue
            sector_summary.append(
                {
                    "sector": sector,
                    "sample_count": count,
                    "avg_pnl_t5": round(float(stats["avg_pnl_t5"]) / count, 4),
                    "avg_alpha": round(float(stats["avg_alpha"]) / count, 4),
                }
            )

        calibrations = sorted(
            self.calibration_store.get_all_calibrations(),
            key=lambda item: (
                -float(item.get("win_rate") or 0.0),
                -int(item.get("total_calls") or 0),
                str(item.get("agent_name") or ""),
            ),
        )
        return {
            "last_backtest_date": last_backtest_date,
            "calibrations": calibrations[:15],
            "sector_summary": sector_summary,
            "recent_matured_episodes": [
                {
                    "trade_date": item.get("trade_date"),
                    "ticker": item.get("ticker"),
                    "action": item.get("action"),
                    "sector": item.get("sector"),
                    "pnl_t5": item.get("pnl_t5"),
                    "alpha_vs_vn30": item.get("alpha_vs_vn30"),
                }
                for item in recent_episodes[:10]
            ],
        }

    def _recent_evaluated_episodes(self, *, limit: int) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM episodic_memory
                WHERE pnl_t5 IS NOT NULL
                ORDER BY trade_date DESC, id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [self._deserialize_episode(row) for row in rows]

    @staticmethod
    def _agent_cards_from_episode(episode: Mapping[str, Any]) -> list[dict[str, Any]]:
        raw_cards = episode.get("agent_cards_json")
        if isinstance(raw_cards, str) and raw_cards.strip():
            try:
                parsed = json.loads(raw_cards)
            except json.JSONDecodeError:
                return []
            return [dict(item) for item in parsed if isinstance(item, Mapping)]
        if isinstance(raw_cards, Sequence):
            return [dict(item) for item in raw_cards if isinstance(item, Mapping)]
        return []

    @staticmethod
    def _deserialize_episode(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        raw_cards = payload.get("agent_cards_json")
        if isinstance(raw_cards, str) and raw_cards.strip():
            try:
                payload["agent_cards_json"] = json.loads(raw_cards)
            except json.JSONDecodeError:
                pass
        return payload

    @staticmethod
    def _fallback_summary(payload: Mapping[str, Any]) -> str:
        lines = [
            "# Tóm tắt phản tư Cognitive Trading",
            "",
            "## Độ chính xác của agent",
        ]
        calibrations = list(payload.get("calibrations") or [])
        if calibrations:
            for item in calibrations[:5]:
                lines.append(
                    "- "
                    f"{item.get('agent_name')} / {item.get('sector')}: "
                    f"win_rate={float(item.get('win_rate') or 0.0):.2%} "
                    f"({int(item.get('correct_calls') or 0)}/{int(item.get('total_calls') or 0)})"
                )
        else:
            lines.append("- Chưa có lịch sử calibration khả dụng.")

        lines.extend(["", "## Bài học theo ngành"])
        sector_summary = list(payload.get("sector_summary") or [])
        if sector_summary:
            for item in sector_summary:
                lines.append(
                    "- "
                    f"{item.get('sector')}: pnl_t5_trung_bình={float(item.get('avg_pnl_t5') or 0.0):.2f}%, "
                    f"alpha_trung_bình={float(item.get('avg_alpha') or 0.0):.2f}%, "
                    f"số_mẫu={int(item.get('sample_count') or 0)}"
                )
        else:
            lines.append("- Chưa có ngành nào đủ điều kiện đánh giá.")

        lines.extend(["", "## Các episode đã trưởng thành gần đây"])
        recent = list(payload.get("recent_matured_episodes") or [])
        if recent:
            for item in recent[:5]:
                lines.append(
                    "- "
                    f"{item.get('trade_date')} {item.get('ticker')} {item.get('action')}: "
                    f"pnl_t5={float(item.get('pnl_t5') or 0.0):.2f}%, "
                    f"alpha_so_với_vn30={float(item.get('alpha_vs_vn30') or 0.0):.2f}%"
                )
        else:
            lines.append("- Không có episode trưởng thành nào khả dụng.")
        return "\n".join(lines)

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


__all__ = ["ReflectionAgent"]
