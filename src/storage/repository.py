"""Repository layer managing atomic SQLite transactions and entity persistence.

Encapsulates SQL statements for tracking scrape runs, upserting canonical product
records by unique URL, and appending point-in-time price observations.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

from src.models import ScrapedItem
from src.storage.database import DatabaseManager


class TrackerRepository:
    """Data access repository for tracker runs, products, and price snapshots."""

    def __init__(self, db_path: Union[Path, str]):
        self.db_path = Path(db_path) if isinstance(db_path, str) else db_path
        self.db_manager = DatabaseManager(self.db_path)
        self.conn = self.db_manager.get_connection()
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Create tables and indexes on the active database connection."""
        self.db_manager.initialize_schema(self.conn)

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        if self.conn:
            self.conn.close()

    def start_scrape_run(self, mode: str) -> int:
        """Register a new scrape run with RUNNING status and return its identifier."""
        started_at = datetime.now(timezone.utc).isoformat()
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO scrape_runs (started_at, mode, status, pages_scraped, items_scraped)
                VALUES (?, ?, 'RUNNING', 0, 0);
                """,
                (started_at, mode),
            )
            return cursor.lastrowid

    def complete_scrape_run(
        self,
        run_id: int,
        status: str,
        pages_scraped: int,
        items_scraped: int,
        error_message: Optional[str] = None,
    ) -> None:
        """Record the completion timestamp, final status, and metrics for a run."""
        completed_at = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                UPDATE scrape_runs
                SET completed_at = ?,
                    status = ?,
                    pages_scraped = ?,
                    items_scraped = ?,
                    error_message = ?
                WHERE id = ?;
                """,
                (completed_at, status, pages_scraped, items_scraped, error_message, run_id),
            )

    def upsert_product(
        self,
        first_arg: Union[sqlite3.Cursor, ScrapedItem],
        second_arg: Union[ScrapedItem, str] = None,
        third_arg: Optional[str] = None,
    ) -> int:
        """Insert a product or update existing details when new attributes are extracted.

        Accepts either (cursor, item, timestamp) during batch transactions or
        (item, timestamp) for standalone operations.
        """
        if isinstance(first_arg, sqlite3.Cursor):
            cursor = first_arg
            item = second_arg
            timestamp = third_arg or datetime.now(timezone.utc).isoformat()
            managed_tx = False
        else:
            item = first_arg
            timestamp = second_arg or datetime.now(timezone.utc).isoformat()
            cursor = self.conn.cursor()
            managed_tx = True

        sql = """
        INSERT INTO products (upc, title, url, thumbnail_url, category, description, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            upc = COALESCE(excluded.upc, products.upc),
            title = excluded.title,
            thumbnail_url = COALESCE(excluded.thumbnail_url, products.thumbnail_url),
            category = COALESCE(excluded.category, products.category),
            description = COALESCE(excluded.description, products.description),
            updated_at = excluded.updated_at
        RETURNING id;
        """
        params = (
            item.upc,
            item.title,
            item.url,
            item.thumbnail_url,
            item.category,
            item.description,
            timestamp,
            timestamp,
        )

        if managed_tx:
            with self.conn:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row[0] if row else row["id"]
        else:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return row[0] if row else row["id"]

    def record_snapshot(
        self,
        first_arg: Union[sqlite3.Cursor, int],
        second_arg: Union[int, ScrapedItem],
        third_arg: Union[int, ScrapedItem, str] = None,
        fourth_arg: Union[ScrapedItem, str] = None,
        fifth_arg: Optional[str] = None,
    ) -> int:
        """Insert a point-in-time observation of price, rating, and stock.

        Supports (cursor, run_id, product_id, item, timestamp) for batch writes and
        (run_id, product_id, item, timestamp) for standalone calls.
        """
        if isinstance(first_arg, sqlite3.Cursor):
            cursor = first_arg
            run_id = second_arg
            product_id = third_arg
            item = fourth_arg
            timestamp = fifth_arg or datetime.now(timezone.utc).isoformat()
            managed_tx = False
        else:
            run_id = first_arg
            product_id = second_arg
            item = third_arg
            timestamp = fourth_arg or datetime.now(timezone.utc).isoformat()
            cursor = self.conn.cursor()
            managed_tx = True

        sql = """
        INSERT INTO price_snapshots (
            run_id, product_id, price_gbp, currency, rating, in_stock, stock_quantity, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id;
        """
        params = (
            run_id,
            product_id,
            item.price_gbp,
            item.currency,
            item.rating,
            1 if item.in_stock else 0,
            item.stock_quantity,
            timestamp,
        )

        if managed_tx:
            with self.conn:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row[0] if row else row["id"]
        else:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return row[0] if row else row["id"]

    def record_batch(self, run_id: int, items: List[ScrapedItem]) -> int:
        """Persist a list of scraped items in an atomic transaction.

        Rolls back the entire batch if an individual record fails, preventing
        partial product updates or orphaned snapshots. Returns the processed count.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.conn:
            cursor = self.conn.cursor()
            count = 0
            for item in items:
                product_id = self.upsert_product(cursor, item, timestamp)
                self.record_snapshot(cursor, run_id, product_id, item, timestamp)
                count += 1
        return count
