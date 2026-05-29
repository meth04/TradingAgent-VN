"""CRUD and lookahead-safe retrieval for cognitive_trading episodic memory."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from cognitive_trading.memory.db import CognitiveDB, init_memory_db

import pandas as pd

from cognitive_trading.config import CognitiveConfig
from cognitive_trading.governance.schemas import AnalysisCard
from vnstock.agents.prompting import Action, normalize_action
from vnstock.database.repo import DataRepository
from tracking_news.app.tickers.vn30 import VN30_TICKERS

_HORIZON_TO_COLUMN = {1: "pnl_t1", 3: "pnl_t3", 5: "pnl_t5", 20: "pnl_t20"}


def _normalize_date(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _to_vnd(raw_price: float | int | None) -> float | None:
    if raw_price is None:
        return None
    return round(float(raw_price) * 1000.0, 4)


@dataclass(slots=True)
class EpisodicStore:
    """Persist episodes and update ref-date-safe outcome metrics in cognitive.db."""

    db_path: Path | str | None = None
    config: CognitiveConfig = CognitiveConfig()
    repo: DataRepository | None = None
    cognitive_db: CognitiveDB | None = None
    _price_history_cache: dict[str, pd.DataFrame] = field(default_factory=dict, init=False, repr=False)

    def save_episode(
        self,
        *,
        trade_date: str,
        ticker: str,
        action: str | Action,
        entry_price: float | None,
        quantity: int | None,
        vn30_close: float | None,
        vn30_change_pct: float | None,
        sector: str | None,
        macro_summary: str | None,
        news_summary: str | None,
        agent_cards: Sequence[AnalysisCard | Mapping[str, Any]],
        debate_summary: str | None,
        cio_reasoning: str | None,
    ) -> int:
        """Insert a new episodic memory row and return the created episode id."""

        normalized_action = normalize_action(action)
        if normalized_action is None:
            raise ValueError(f"Unsupported action for episodic memory: {action}")

        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO episodic_memory (
                  trade_date,
                  ticker,
                  action,
                  entry_price,
                  quantity,
                  vn30_close,
                  vn30_change_pct,
                  sector,
                  macro_summary,
                  news_summary,
                  agent_cards_json,
                  debate_summary,
                  cio_reasoning,
                  embedding
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    trade_date,
                    ticker.upper().strip(),
                    normalized_action.value,
                    float(entry_price) if entry_price is not None else None,
                    int(quantity) if quantity is not None else None,
                    float(vn30_close) if vn30_close is not None else None,
                    float(vn30_change_pct) if vn30_change_pct is not None else None,
                    str(sector).strip().lower() if sector else None,
                    str(macro_summary).strip() if macro_summary else None,
                    str(news_summary).strip() if news_summary else None,
                    json.dumps(
                        self._serialize_agent_cards(agent_cards),
                        ensure_ascii=False,
                        default=str,
                    ),
                    str(debate_summary).strip() if debate_summary else None,
                    str(cio_reasoning).strip() if cio_reasoning else None,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def get_episode(self, episode_id: int) -> dict[str, Any] | None:
        """Return one episode row by id."""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM episodic_memory WHERE id = ?",
                (int(episode_id),),
            ).fetchone()
        return self._row_to_dict(row)

    def delete_episode(self, episode_id: int) -> bool:
        """Delete one episode row by id."""

        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM episodic_memory WHERE id = ?",
                (int(episode_id),),
            )
            connection.commit()
            return cursor.rowcount > 0

    def update_outcome(self, *, episode_id: int, horizon_days: int) -> dict[str, Any] | None:
        """Update one outcome horizon column plus alpha_vs_vn30 for an episode."""

        column = _HORIZON_TO_COLUMN.get(int(horizon_days))
        if column is None:
            raise ValueError("horizon_days must be one of 1, 3, 5, or 20")

        episode = self.get_episode(episode_id)
        if episode is None:
            return None

        entry_price = float(episode.get("entry_price") or 0.0)
        if entry_price <= 0:
            return None

        repo, should_close = self._get_repo()
        try:
            history = self._price_history(repo, str(episode["ticker"]))
            exit_price = self._future_close_vnd(
                history=history,
                trade_date=str(episode["trade_date"]),
                horizon_days=int(horizon_days),
            )
            if exit_price is None:
                return None

            pnl_pct = round(((exit_price - entry_price) / entry_price) * 100.0, 4)
            alpha_vs_vn30 = self._benchmark_alpha_pct(
                repo=repo,
                trade_date=str(episode["trade_date"]),
                horizon_days=int(horizon_days),
                stock_return_pct=pnl_pct,
            )

            with self._connection() as connection:
                connection.execute(
                    f"UPDATE episodic_memory SET {column} = ?, alpha_vs_vn30 = ? WHERE id = ?",
                    (
                        pnl_pct,
                        alpha_vs_vn30,
                        int(episode_id),
                    ),
                )
                connection.commit()
        finally:
            if should_close:
                repo.close()

        return self.get_episode(episode_id)

    def find_similar(
        self,
        *,
        current_ref_date: str,
        ticker: str | None = None,
        sector: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Return recent prior episodes with optional ticker and sector filters."""

        query = ["SELECT * FROM episodic_memory WHERE trade_date < ?"]
        params: list[Any] = [current_ref_date]
        if ticker:
            query.append("AND ticker = ?")
            params.append(ticker.upper().strip())
        if sector:
            query.append("AND sector = ?")
            params.append(sector.strip().lower())
        query.append("ORDER BY trade_date DESC, id DESC LIMIT ?")
        params.append(max(1, int(top_k)))

        with self._connection() as connection:
            rows = connection.execute(" ".join(query), params).fetchall()
        return [self._row_to_dict(row) for row in rows if row is not None]

    def get_recent_episodes(self, *, ticker: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return the most recent episodes for one ticker."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM episodic_memory
                WHERE ticker = ?
                ORDER BY trade_date DESC, id DESC
                LIMIT ?
                """,
                (ticker.upper().strip(), max(1, int(limit))),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows if row is not None]

    def get_recent_session_memory(
        self,
        *,
        ticker: str,
        current_ref_date: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return compact summaries from the most recent prior sessions for one ticker."""

        recent = self.find_similar(
            current_ref_date=current_ref_date,
            ticker=ticker,
            sector=None,
            top_k=max(1, int(limit)),
        )
        memory: list[dict[str, Any]] = []
        for item in recent[:limit]:
            cards = item.get("agent_cards_json") or []
            top_agents = []
            if isinstance(cards, list):
                for card in cards[:3]:
                    if isinstance(card, Mapping):
                        top_agents.append(
                            {
                                "agent_name": card.get("agent_name"),
                                "action": card.get("action"),
                                "confidence": card.get("confidence_calibrated") or card.get("confidence_raw"),
                            }
                        )
            memory.append(
                {
                    "trade_date": item.get("trade_date"),
                    "ticker": item.get("ticker"),
                    "action": item.get("action"),
                    "entry_price": item.get("entry_price"),
                    "quantity": item.get("quantity"),
                    "debate_summary": item.get("debate_summary"),
                    "cio_reasoning": item.get("cio_reasoning"),
                    "pnl_t5": item.get("pnl_t5"),
                    "alpha_vs_vn30": item.get("alpha_vs_vn30"),
                    "top_agents": top_agents,
                }
            )
        return memory

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

    def _get_repo(self) -> tuple[DataRepository, bool]:
        if self.repo is not None:
            return self.repo, False
        return DataRepository(), True

    def _price_history(self, repo: DataRepository, ticker: str) -> pd.DataFrame:
        normalized_ticker = ticker.upper().strip()
        cached = self._price_history_cache.get(normalized_ticker)
        if cached is not None:
            return cached

        history = repo.get_price_history(normalized_ticker, days=0)
        if history.empty:
            self._price_history_cache[normalized_ticker] = history
            return history

        normalized = history.copy()
        normalized["date"] = pd.to_datetime(normalized["date"]).dt.normalize()
        normalized = normalized.sort_values("date")
        normalized = normalized.drop_duplicates(subset=["date"], keep="last")
        normalized = normalized.reset_index(drop=True)
        self._price_history_cache[normalized_ticker] = normalized
        return normalized

    @staticmethod
    def _future_close_vnd(
        *,
        history: pd.DataFrame,
        trade_date: str,
        horizon_days: int,
    ) -> float | None:
        if history.empty:
            return None
        trade_ts = _normalize_date(trade_date)
        future_rows = history[history["date"] > trade_ts]
        if len(future_rows) < horizon_days:
            return None
        return _to_vnd(float(future_rows.iloc[horizon_days - 1]["close"]))

    def _benchmark_alpha_pct(
        self,
        *,
        repo: DataRepository,
        trade_date: str,
        horizon_days: int,
        stock_return_pct: float,
    ) -> float | None:
        benchmark_returns: list[float] = []
        trade_ts = _normalize_date(trade_date)
        for benchmark_ticker in VN30_TICKERS:
            history = self._price_history(repo, str(benchmark_ticker))
            if history.empty:
                continue

            base_rows = history[history["date"] <= trade_ts]
            future_rows = history[history["date"] > trade_ts]
            if base_rows.empty or len(future_rows) < horizon_days:
                continue

            base_close = _to_vnd(float(base_rows.iloc[-1]["close"]))
            target_close = _to_vnd(float(future_rows.iloc[horizon_days - 1]["close"]))
            if base_close is None or target_close is None or base_close <= 0:
                continue

            benchmark_returns.append(((target_close - base_close) / base_close) * 100.0)

        if not benchmark_returns:
            return None
        benchmark_return = sum(benchmark_returns) / len(benchmark_returns)
        return round(float(stock_return_pct) - float(benchmark_return), 4)

    @staticmethod
    def _serialize_agent_cards(
        agent_cards: Sequence[AnalysisCard | Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for item in agent_cards:
            if isinstance(item, AnalysisCard):
                payload.append(item.model_dump(mode="json", by_alias=True))
            else:
                payload.append(dict(item))
        return payload

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        payload = dict(row)
        raw_cards = payload.get("agent_cards_json")
        if isinstance(raw_cards, str) and raw_cards.strip():
            try:
                payload["agent_cards_json"] = json.loads(raw_cards)
            except json.JSONDecodeError:
                pass
        return payload


__all__ = ["EpisodicStore"]
