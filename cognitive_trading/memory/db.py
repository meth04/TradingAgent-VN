"""Shared SQLite connection helper for cognitive_trading memory stores."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from cognitive_trading.config import CognitiveConfig

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS episodic_memory (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_date TEXT NOT NULL,
  ticker TEXT NOT NULL,
  action TEXT NOT NULL,
  entry_price REAL,
  quantity INTEGER,
  vn30_close REAL,
  vn30_change_pct REAL,
  sector TEXT,
  macro_summary TEXT,
  news_summary TEXT,
  agent_cards_json TEXT,
  debate_summary TEXT,
  cio_reasoning TEXT,
  pnl_t1 REAL,
  pnl_t3 REAL,
  pnl_t5 REAL,
  pnl_t20 REAL,
  alpha_vs_vn30 REAL,
  embedding BLOB,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_episodic_memory_trade_date
  ON episodic_memory(trade_date);
CREATE INDEX IF NOT EXISTS idx_episodic_memory_ticker_trade_date
  ON episodic_memory(ticker, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_episodic_memory_action_trade_date
  ON episodic_memory(action, trade_date DESC);

CREATE TABLE IF NOT EXISTS calibration_store (
  agent_name TEXT NOT NULL,
  sector TEXT NOT NULL,
  total_calls INTEGER DEFAULT 0,
  correct_calls INTEGER DEFAULT 0,
  win_rate REAL DEFAULT 0.5,
  last_updated TEXT,
  PRIMARY KEY (agent_name, sector)
);
CREATE INDEX IF NOT EXISTS idx_calibration_store_sector
  ON calibration_store(sector);

CREATE TABLE IF NOT EXISTS strategy_memory (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  pattern_description TEXT,
  target_sectors TEXT,
  recommended_action TEXT,
  avg_alpha REAL,
  sample_count INTEGER,
  status TEXT DEFAULT 'active',
  invalidation_condition TEXT,
  created_at TEXT,
  last_used TEXT,
  consecutive_losses INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_strategy_memory_status
  ON strategy_memory(status);
CREATE INDEX IF NOT EXISTS idx_strategy_memory_last_used
  ON strategy_memory(last_used);
"""


def init_memory_db(db_path: Path | str | None = None) -> Path:
    """Create the cognitive SQLite schema if it does not already exist."""

    target_path = Path(db_path) if db_path is not None else CognitiveConfig().memory_db_path
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(target_path) as connection:
        connection.executescript(DDL)
        connection.commit()

    return target_path


@dataclass(slots=True)
class CognitiveDB:
    """Own a reusable SQLite connection for memory-heavy cognitive components."""

    db_path: Path | str | None = None
    config: CognitiveConfig = CognitiveConfig()
    _resolved_path: Path = field(init=False, repr=False)
    _connection: sqlite3.Connection = field(init=False, repr=False)

    def __post_init__(self) -> None:
        target = self.db_path if self.db_path is not None else self.config.memory_db_path
        self._resolved_path = init_memory_db(target)
        self._connection = sqlite3.connect(self._resolved_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")

    @property
    def path(self) -> Path:
        return self._resolved_path

    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        self._connection.close()


__all__ = ["CognitiveDB", "DDL", "init_memory_db"]
