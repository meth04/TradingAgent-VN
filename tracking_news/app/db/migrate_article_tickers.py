import logging
import sqlite3

from app.db.conn import connect

logger = logging.getLogger(__name__)


DDL = """
CREATE TABLE IF NOT EXISTS article_tickers (
  ticker TEXT NOT NULL,
  article_id INTEGER NOT NULL,
  PRIMARY KEY (ticker, article_id)
);
CREATE INDEX IF NOT EXISTS idx_article_tickers_article
  ON article_tickers(article_id);
CREATE INDEX IF NOT EXISTS idx_article_tickers_ticker
  ON article_tickers(ticker, article_id);
"""


def _populate_article_tickers(con: sqlite3.Connection) -> int:
    cur = con.execute(
        """
        INSERT OR IGNORE INTO article_tickers(ticker, article_id)
        SELECT trim(value), a.id
        FROM articles AS a
        CROSS JOIN json_each(a.tickers_json)
        WHERE a.tickers_json IS NOT NULL
          AND a.tickers_json != '[]'
          AND json_valid(a.tickers_json)
          AND trim(value) != ''
        """
    )
    return cur.rowcount


def main() -> None:
    con = connect()
    try:
        con.executescript(DDL)
        inserted = _populate_article_tickers(con)
        con.commit()
        logger.info("migration complete", extra={"inserted_rows": inserted})
    finally:
        con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
