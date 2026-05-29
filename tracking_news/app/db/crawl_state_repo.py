import sqlite3
from datetime import UTC, datetime


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def upsert_crawl_state(
    con: sqlite3.Connection,
    *,
    source: str,
    section: str,
    status: str,
    error: str | None = None,
    last_published_at: str | None = None,
) -> None:
    con.execute(
        """
        insert into crawl_state (source, section, last_published_at, last_run_at, status, error)
        values (?, ?, ?, ?, ?, ?)
        on conflict(source, section) do update set
            last_published_at = excluded.last_published_at,
            last_run_at = excluded.last_run_at,
            status = excluded.status,
            error = excluded.error
        """,
        (source, section, last_published_at, _now_iso(), status, error),
    )
    con.commit()
