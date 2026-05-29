"""Persist and read analysis history JSON files in app/data/history/."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from bootstrap import APP_DATA_DIR

HISTORY_DIR = APP_DATA_DIR / "history"


def _ensure_dir() -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def save_analysis(analysis_id: str, data: Dict[str, Any]) -> None:
    _ensure_dir()
    path = HISTORY_DIR / f"{analysis_id}.json"
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def list_analyses() -> List[Dict[str, Any]]:
    _ensure_dir()
    results: List[Dict[str, Any]] = []
    for f in sorted(HISTORY_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        results.append(
            {
                "id": data.get("id") or f.stem,
                "timestamp": data.get("timestamp"),
                "tickers": data.get("tickers") or [],
                "workflow": data.get("workflow"),
                "summary": data.get("summary") or "",
            }
        )
    return results


def get_analysis(analysis_id: str) -> Optional[Dict[str, Any]]:
    path = HISTORY_DIR / f"{analysis_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
