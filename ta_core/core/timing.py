"""Reusable timing utilities for backtest observability."""

from __future__ import annotations

import logging
import time
from threading import RLock
from typing import Mapping

logger = logging.getLogger("vnstock.timing")


class _TimerContext:
    """Context manager returned by Timer.track()."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.start = 0.0

    def __enter__(self) -> "_TimerContext":
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        elapsed = time.perf_counter() - self.start
        Timer._record(self.name, elapsed)
        return False


class Timer:
    """Collect named duration samples and expose aggregate summaries."""

    _records: dict[str, list[float]] = {}
    _lock = RLock()

    @classmethod
    def track(cls, name: str) -> _TimerContext:
        return _TimerContext(name)

    @classmethod
    def _record(cls, name: str, elapsed: float) -> None:
        with cls._lock:
            cls._records.setdefault(name, []).append(float(elapsed))
        logger.info("Timer %s: %.4fs", name, elapsed)

    @classmethod
    def reset(cls, prefix: str | None = None) -> None:
        with cls._lock:
            if prefix is None:
                cls._records.clear()
                return
            cls._records = {
                name: values
                for name, values in cls._records.items()
                if not name.startswith(prefix)
            }

    @classmethod
    def snapshot(cls) -> dict[str, int]:
        with cls._lock:
            return {name: len(values) for name, values in cls._records.items()}

    @classmethod
    def summary(cls, prefix: str | None = None) -> dict[str, dict[str, float | int]]:
        with cls._lock:
            items = {
                name: list(values)
                for name, values in cls._records.items()
                if prefix is None or name.startswith(prefix)
            }
        return cls._aggregate(items)

    @classmethod
    def summary_since(
        cls,
        snapshot: Mapping[str, int],
        prefix: str | None = None,
    ) -> dict[str, dict[str, float | int]]:
        with cls._lock:
            items: dict[str, list[float]] = {}
            for name, values in cls._records.items():
                if prefix is not None and not name.startswith(prefix):
                    continue
                start_idx = min(int(snapshot.get(name, 0)), len(values))
                delta = list(values[start_idx:])
                if delta:
                    items[name] = delta
        return cls._aggregate(items)

    @staticmethod
    def _aggregate(samples: Mapping[str, list[float]]) -> dict[str, dict[str, float | int]]:
        summary: dict[str, dict[str, float | int]] = {}
        for name in sorted(samples):
            values = samples[name]
            if not values:
                continue
            total = float(sum(values))
            count = len(values)
            summary[name] = {
                "count": count,
                "total_seconds": round(total, 6),
                "avg_seconds": round(total / count, 6),
                "max_seconds": round(max(values), 6),
            }
        return summary


__all__ = ["Timer"]
