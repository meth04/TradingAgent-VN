import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.db.conn import connect
from app.db.init_db import init_db
from app.extract.http_client import build_client, fetch_html


@dataclass(frozen=True, slots=True)
class ZoneTarget:
    zone_id: str
    page_from: int
    page_to: int


def _timelinelist_url(zone_id: str, page_number: int) -> str:
    return f"https://cafef.vn/timelinelist/{zone_id}/{page_number}.chn"


def _parse_zone_targets(raw: str) -> list[ZoneTarget]:
    targets: list[ZoneTarget] = []
    for chunk in raw.split(","):
        item = chunk.strip()
        if not item:
            continue
        if ":" in item:
            zone_id, range_part = item.split(":", 1)
            if "-" in range_part:
                start_raw, end_raw = range_part.split("-", 1)
                page_from = int(start_raw)
                page_to = int(end_raw)
            else:
                page_from = int(range_part)
                page_to = page_from
        else:
            zone_id = item
            page_from = 1
            page_to = 1
        targets.append(ZoneTarget(zone_id=zone_id.strip(), page_from=page_from, page_to=page_to))
    if not targets:
        raise ValueError("CAFEF_TIMELINELIST_TARGETS is empty")
    return targets


def _extract_rows(html: str, *, page_url: str, zone_id: str, page_number: int) -> list[tuple]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[tuple] = []

    for item_rank, node in enumerate(soup.select(".tlitem"), start=1):
        title_link = node.select_one("h3 a[href]")
        article_url = None
        title = None
        if title_link is not None:
            href = title_link.get("href")
            if isinstance(href, str) and href.strip():
                article_url = urljoin(page_url, href.strip())
            title = title_link.get_text(" ", strip=True) or None

        if not article_url:
            continue

        published_at_raw = None
        time_node = node.select_one("span.time[title], p.time[data-time]")
        if time_node is not None:
            published_at_raw = time_node.get("title") or time_node.get("data-time")

        summary_node = node.select_one(".sapo")
        summary_text = summary_node.get_text(" ", strip=True) if summary_node is not None else None

        image_node = node.select_one("img[src]")
        image_url = image_node.get("src") if image_node is not None else None

        rows.append(
            (
                zone_id,
                page_number,
                page_url,
                item_rank,
                node.get("data-id"),
                article_url,
                title,
                published_at_raw,
                summary_text,
                image_url,
                str(node),
            )
        )

    return rows


def _insert_rows(con: sqlite3.Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    before = con.total_changes
    con.executemany(
        """
        insert or ignore into cafef_timelinelist_raw (
          zone_id,
          page_number,
          page_url,
          item_rank,
          article_id,
          article_url,
          title,
          published_at_raw,
          summary_text,
          image_url,
          raw_item_html
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.commit()
    return con.total_changes - before


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    db_path = os.getenv("NEWS_DB_PATH", str(project_root / "data" / "news.db"))
    targets = _parse_zone_targets(os.getenv("CAFEF_TIMELINELIST_TARGETS", "18839:1-10"))
    init_db(db_path)

    total_pages = 0
    total_rows = 0
    total_inserted = 0

    with connect(db_path) as con, build_client() as client:
        for target in targets:
            zone_pages = 0
            zone_rows = 0
            zone_inserted = 0
            for page_number in range(target.page_from, target.page_to + 1):
                page_url = _timelinelist_url(target.zone_id, page_number)
                html = fetch_html(page_url, client=client, rate_limit_seconds=0.0)
                rows = _extract_rows(
                    html,
                    page_url=page_url,
                    zone_id=target.zone_id,
                    page_number=page_number,
                )
                inserted = _insert_rows(con, rows)
                total_pages += 1
                total_rows += len(rows)
                total_inserted += inserted
                zone_pages += 1
                zone_rows += len(rows)
                zone_inserted += inserted
                print(
                    f"[zone:{target.zone_id}]",
                    f"page={page_number}",
                    f"items={len(rows)}",
                    f"inserted={inserted}",
                )
            print(
                f"[zone:{target.zone_id}] done",
                f"pages={zone_pages}",
                f"items={zone_rows}",
                f"inserted={zone_inserted}",
            )

    print(
        "cafef_timelinelist_raw completed:",
        f"targets={len(targets)}",
        f"pages={total_pages}",
        f"items={total_rows}",
        f"inserted={total_inserted}",
        f"db_path={db_path}",
    )


if __name__ == "__main__":
    main()
