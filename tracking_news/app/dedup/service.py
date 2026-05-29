import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from app.dedup.hashers import hamming_distance


@dataclass(frozen=True, slots=True)
class DedupDecision:
    is_duplicate: bool
    reason: str | None = None
    canonical_id: int | None = None


def find_duplicate(
    con: sqlite3.Connection,
    *,
    published_date: str,
    content_sha256: str,
    simhash64: int,
    simhash_bucket: int,
    max_distance: int = 3,
) -> DedupDecision:
    exact_row = con.execute(
        "select id from articles where content_sha256 = ? limit 1",
        (content_sha256,),
    ).fetchone()
    if exact_row:
        return DedupDecision(True, "exact_sha256", int(exact_row["id"]))

    anchor_date = date.fromisoformat(published_date)
    start_date = (anchor_date - timedelta(days=1)).isoformat()
    end_date = (anchor_date + timedelta(days=1)).isoformat()
    candidate_rows = con.execute(
        """
        select id, simhash64
        from articles
        where simhash_bucket = ?
          and published_date between ? and ?
        """,
        (simhash_bucket, start_date, end_date),
    ).fetchall()

    for row in candidate_rows:
        if hamming_distance(simhash64, int(row["simhash64"])) <= max_distance:
            return DedupDecision(True, "near_simhash", int(row["id"]))

    return DedupDecision(False)
