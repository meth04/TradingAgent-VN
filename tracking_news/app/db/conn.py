import sqlite3

from app.config import NEWS_DB_PATH


def connect(db_path: str = NEWS_DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con
