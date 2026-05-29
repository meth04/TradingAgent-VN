import os
import sqlite3

from app.config import NEWS_DB_PATH

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL,
  category TEXT,
  seed_section TEXT,
  topic_label TEXT,
  published_at TEXT NOT NULL,
  published_date TEXT NOT NULL,
  content_text TEXT NOT NULL,
  content_html TEXT,
  raw_html TEXT,
  tickers_json TEXT,
  fomo_score REAL NOT NULL,
  fomo_explain_json TEXT,
  content_sha256 TEXT NOT NULL UNIQUE,
  simhash64 INTEGER NOT NULL,
  simhash_bucket INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_articles_published_at
  ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_source_published_at
  ON articles(source, published_at);
CREATE INDEX IF NOT EXISTS idx_articles_category_published_at
  ON articles(category, published_at);
CREATE INDEX IF NOT EXISTS idx_articles_simhash_bucket_date
  ON articles(simhash_bucket, published_date);
CREATE INDEX IF NOT EXISTS idx_articles_topic_published_desc
  ON articles(topic_label, published_date DESC);
CREATE INDEX IF NOT EXISTS idx_articles_pubdate_desc
  ON articles(published_date DESC, id);

CREATE TABLE IF NOT EXISTS article_tickers (
  ticker TEXT NOT NULL,
  article_id INTEGER NOT NULL,
  PRIMARY KEY (ticker, article_id)
);
CREATE INDEX IF NOT EXISTS idx_article_tickers_article
  ON article_tickers(article_id);
CREATE INDEX IF NOT EXISTS idx_article_tickers_ticker
  ON article_tickers(ticker, article_id);

CREATE TABLE IF NOT EXISTS crawl_state (
  source TEXT NOT NULL,
  section TEXT NOT NULL,
  last_published_at TEXT,
  last_run_at TEXT,
  status TEXT,
  error TEXT,
  PRIMARY KEY (source, section)
);

CREATE TABLE IF NOT EXISTS ingest_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT,
  finished_at TEXT,
  mode TEXT,
  inserted_count INTEGER DEFAULT 0,
  dropped_no_date_count INTEGER DEFAULT 0,
  dropped_irrelevant_count INTEGER DEFAULT 0,
  dropped_out_of_window_count INTEGER DEFAULT 0,
  dedup_dropped_count INTEGER DEFAULT 0,
  error TEXT
);

CREATE TABLE IF NOT EXISTS ingest_section_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  source TEXT NOT NULL,
  section TEXT NOT NULL,
  section_url TEXT,
  pages_scanned INTEGER DEFAULT 0,
  discovered_raw INTEGER DEFAULT 0,
  discovered_unique INTEGER DEFAULT 0,
  processed_urls INTEGER DEFAULT 0,
  inserted_count INTEGER DEFAULT 0,
  dropped_no_date_count INTEGER DEFAULT 0,
  dropped_irrelevant_count INTEGER DEFAULT 0,
  dropped_out_of_window_count INTEGER DEFAULT 0,
  dedup_dropped_count INTEGER DEFAULT 0,
  failed_count INTEGER DEFAULT 0,
  latest_published_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (run_id) REFERENCES ingest_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_ingest_section_runs_run_id
  ON ingest_section_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_ingest_section_runs_source_section
  ON ingest_section_runs(source, section, created_at);

CREATE TABLE IF NOT EXISTS cafef_timelinelist_raw (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  zone_id TEXT NOT NULL,
  page_number INTEGER NOT NULL,
  page_url TEXT NOT NULL,
  item_rank INTEGER NOT NULL,
  article_id TEXT,
  article_url TEXT NOT NULL,
  title TEXT,
  published_at_raw TEXT,
  summary_text TEXT,
  image_url TEXT,
  raw_item_html TEXT,
  collected_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(zone_id, page_number, item_rank, article_url)
);

CREATE INDEX IF NOT EXISTS idx_cafef_timelinelist_raw_zone_page
  ON cafef_timelinelist_raw(zone_id, page_number, item_rank);
CREATE INDEX IF NOT EXISTS idx_cafef_timelinelist_raw_article_url
  ON cafef_timelinelist_raw(article_url);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts
USING fts5(title, content_text, content='articles', content_rowid='id');

CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
  INSERT INTO articles_fts(rowid, title, content_text)
  VALUES (new.id, new.title, new.content_text);
END;

CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, title, content_text)
  VALUES('delete', old.id, old.title, old.content_text);
END;

CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, title, content_text)
  VALUES('delete', old.id, old.title, old.content_text);
  INSERT INTO articles_fts(rowid, title, content_text)
  VALUES (new.id, new.title, new.content_text);
END;
"""


def _ensure_ingest_runs_columns(con: sqlite3.Connection) -> None:
    columns = {row[1] for row in con.execute("pragma table_info(ingest_runs)").fetchall()}
    if "dropped_irrelevant_count" not in columns:
        con.execute("alter table ingest_runs add column dropped_irrelevant_count INTEGER DEFAULT 0")
    if "dropped_out_of_window_count" not in columns:
        con.execute(
            "alter table ingest_runs add column dropped_out_of_window_count INTEGER DEFAULT 0"
        )


def _ensure_articles_columns(con: sqlite3.Connection) -> None:
    columns = {row[1] for row in con.execute("pragma table_info(articles)").fetchall()}
    if "seed_section" not in columns:
        con.execute("alter table articles add column seed_section TEXT")
    if "topic_label" not in columns:
        con.execute("alter table articles add column topic_label TEXT")

    con.execute(
        "create index if not exists idx_articles_topic_label_published_date on articles(topic_label, published_date)"
    )
    con.execute(
        "create index if not exists idx_articles_topic_published_desc on articles(topic_label, published_date desc)"
    )
    con.execute(
        "create index if not exists idx_articles_seed_section_published_date on articles(seed_section, published_date)"
    )
    con.execute(
        "create index if not exists idx_articles_pubdate_desc on articles(published_date desc, id)"
    )


def _ensure_article_tickers_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        create table if not exists article_tickers (
          ticker TEXT NOT NULL,
          article_id INTEGER NOT NULL,
          PRIMARY KEY (ticker, article_id)
        )
        """
    )
    con.execute(
        "create index if not exists idx_article_tickers_article on article_tickers(article_id)"
    )
    con.execute(
        "create index if not exists idx_article_tickers_ticker on article_tickers(ticker, article_id)"
    )


def _ensure_ingest_section_runs_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        create table if not exists ingest_section_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL,
          source TEXT NOT NULL,
          section TEXT NOT NULL,
          section_url TEXT,
          pages_scanned INTEGER DEFAULT 0,
          discovered_raw INTEGER DEFAULT 0,
          discovered_unique INTEGER DEFAULT 0,
          processed_urls INTEGER DEFAULT 0,
          inserted_count INTEGER DEFAULT 0,
          dropped_no_date_count INTEGER DEFAULT 0,
          dropped_irrelevant_count INTEGER DEFAULT 0,
          dropped_out_of_window_count INTEGER DEFAULT 0,
          dedup_dropped_count INTEGER DEFAULT 0,
          failed_count INTEGER DEFAULT 0,
          latest_published_at TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (run_id) REFERENCES ingest_runs(id)
        )
        """
    )
    con.execute(
        "create index if not exists idx_ingest_section_runs_run_id on ingest_section_runs(run_id)"
    )
    con.execute(
        "create index if not exists idx_ingest_section_runs_source_section on ingest_section_runs(source, section, created_at)"
    )


def _ensure_cafef_timelinelist_raw_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        create table if not exists cafef_timelinelist_raw (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          zone_id TEXT NOT NULL,
          page_number INTEGER NOT NULL,
          page_url TEXT NOT NULL,
          item_rank INTEGER NOT NULL,
          article_id TEXT,
          article_url TEXT NOT NULL,
          title TEXT,
          published_at_raw TEXT,
          summary_text TEXT,
          image_url TEXT,
          raw_item_html TEXT,
          collected_at TEXT NOT NULL DEFAULT (datetime('now')),
          UNIQUE(zone_id, page_number, item_rank, article_url)
        )
        """
    )
    con.execute(
        "create index if not exists idx_cafef_timelinelist_raw_zone_page on cafef_timelinelist_raw(zone_id, page_number, item_rank)"
    )
    con.execute(
        "create index if not exists idx_cafef_timelinelist_raw_article_url on cafef_timelinelist_raw(article_url)"
    )


def init_db(db_path: str = NEWS_DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(DDL)
        _ensure_ingest_runs_columns(con)
        _ensure_articles_columns(con)
        _ensure_article_tickers_table(con)
        _ensure_ingest_section_runs_table(con)
        _ensure_cafef_timelinelist_raw_table(con)
        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    init_db()
    print(f"Initialized DB at: {NEWS_DB_PATH}")
