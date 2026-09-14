import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("GROCERY_DB_PATH", os.path.expanduser("~/grocery-shopper-data/grocery.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
  name TEXT PRIMARY KEY,
  position INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT,
  interchangeable INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  default_store INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT,
  staple INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS checked (
  item_id TEXT PRIMARY KEY REFERENCES items(id),
  qty INTEGER NOT NULL DEFAULT 1,
  store_override INTEGER,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY,
  finalized_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id TEXT NOT NULL REFERENCES orders(id),
  item_id TEXT,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  store TEXT NOT NULL,
  qty INTEGER NOT NULL
);
"""


def _ensure_column(conn, table, column, decl):
    """CREATE TABLE IF NOT EXISTS leaves an existing table alone, so columns
    added after a database was first created need an explicit ALTER. Table and
    column names here are literals from this module, never request input."""
    existing = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "items", "staple", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "categories", "interchangeable", "INTEGER NOT NULL DEFAULT 0")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
