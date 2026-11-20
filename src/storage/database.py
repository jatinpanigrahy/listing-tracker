"""SQLite database manager, connection factory, and schema initialization.

Configures Write-Ahead Logging (WAL) and foreign key constraints to allow
concurrent readers alongside periodic batch writes while protecting relational
integrity between scrape runs, product entities, and price snapshots.
"""

import sqlite3
from pathlib import Path
from typing import Union


SCHEMA_DDL = """
-- Track individual scraping executions and run metrics.
CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    mode TEXT NOT NULL,
    pages_scraped INTEGER DEFAULT 0,
    items_scraped INTEGER DEFAULT 0,
    status TEXT NOT NULL CHECK(status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    error_message TEXT
);

-- Canonical catalog of unique tracked products identified by their URL.
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upc TEXT UNIQUE,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    thumbnail_url TEXT,
    category TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Point-in-time price, rating, and stock observations.
CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    price_gbp REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'GBP',
    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
    in_stock INTEGER NOT NULL CHECK(in_stock IN (0, 1)),
    stock_quantity INTEGER,
    scraped_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES scrape_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
);

-- Query acceleration indexes for joins, URL deduplication, and time-series sorting.
CREATE INDEX IF NOT EXISTS idx_products_url ON products(url);
CREATE INDEX IF NOT EXISTS idx_products_upc ON products(upc);
CREATE INDEX IF NOT EXISTS idx_snapshots_product_id ON price_snapshots(product_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_run_id ON price_snapshots(run_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_scraped_at ON price_snapshots(scraped_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_product_scraped ON price_snapshots(product_id, scraped_at DESC);
"""


class DatabaseManager:
    """Manages SQLite connections and applies database schema migrations."""

    def __init__(self, db_path: Union[Path, str]):
        self.db_path = Path(db_path) if isinstance(db_path, str) else db_path

    def get_connection(self) -> sqlite3.Connection:
        """Create and configure a new SQLite connection.

        Enforces row factory mapping, foreign key checks, WAL journaling on disk,
        and a 5-second busy timeout to wait out brief write locks.
        """
        # If writing to disk, ensure the destination directory exists.
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        # Execute pragmas directly on the newly created connection.
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.execute("PRAGMA synchronous = NORMAL;")

        # In-memory databases do not support or need WAL mode.
        if str(self.db_path) != ":memory:":
            cursor.execute("PRAGMA journal_mode = WAL;")

        cursor.close()
        return conn

    def initialize_schema(self, conn: sqlite3.Connection = None) -> None:
        """Execute DDL statements to set up tables and indexes idempotently."""
        close_conn = False
        if conn is None:
            conn = self.get_connection()
            close_conn = True

        try:
            with conn:
                conn.executescript(SCHEMA_DDL)
        finally:
            if close_conn:
                conn.close()
