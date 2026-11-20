"""Unit tests for the SQLite storage layer and repository pattern."""

import sqlite3
import pytest

from src.models import ScrapedItem
from src.storage.repository import TrackerRepository


def test_database_initialization(in_memory_repo: TrackerRepository):
    """Verify that all schema tables and indexes are created on startup."""
    cursor = in_memory_repo.conn.cursor()

    # Query master table for registered table names.
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row["name"] for row in cursor.fetchall()}
    assert "scrape_runs" in tables
    assert "products" in tables
    assert "price_snapshots" in tables

    # Query master table for indexes to ensure performance indexes are in place.
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
    indexes = {row["name"] for row in cursor.fetchall()}
    assert "idx_products_url" in indexes
    assert "idx_products_upc" in indexes
    assert "idx_snapshots_product_id" in indexes
    assert "idx_snapshots_run_id" in indexes
    assert "idx_snapshots_scraped_at" in indexes
    assert "idx_snapshots_product_scraped" in indexes


def test_scrape_run_lifecycle(in_memory_repo: TrackerRepository):
    """Verify that scrape runs track start, progress metrics, and completion."""
    run_id = in_memory_repo.start_scrape_run(mode="fast")
    assert isinstance(run_id, int)
    assert run_id > 0

    cursor = in_memory_repo.conn.cursor()
    cursor.execute("SELECT status, completed_at FROM scrape_runs WHERE id = ?;", (run_id,))
    row = cursor.fetchone()
    assert row["status"] == "RUNNING"
    assert row["completed_at"] is None

    in_memory_repo.complete_scrape_run(
        run_id=run_id,
        status="SUCCESS",
        pages_scraped=3,
        items_scraped=60,
    )

    cursor.execute(
        "SELECT status, completed_at, pages_scraped, items_scraped FROM scrape_runs WHERE id = ?;",
        (run_id,),
    )
    completed_row = cursor.fetchone()
    assert completed_row["status"] == "SUCCESS"
    assert completed_row["completed_at"] is not None
    assert completed_row["pages_scraped"] == 3
    assert completed_row["items_scraped"] == 60


def test_product_upsert_idempotency(in_memory_repo: TrackerRepository):
    """Verify that repeated writes for the same product URL update fields rather than duplicate."""
    initial_item = ScrapedItem(
        title="Sample Book Title",
        url="https://books.toscrape.com/catalogue/sample_1/index.html",
        price_gbp=25.00,
        rating=3,
        in_stock=True,
    )
    product_id_1 = in_memory_repo.upsert_product(initial_item)

    # Secondary scrape with deep details (UPC and category discovered).
    enriched_item = ScrapedItem(
        title="Sample Book Title",
        url="https://books.toscrape.com/catalogue/sample_1/index.html",
        price_gbp=25.00,
        rating=3,
        in_stock=True,
        upc="abc123xyz789",
        category="Science Fiction",
        description="A book description discovered on product detail page.",
    )
    product_id_2 = in_memory_repo.upsert_product(enriched_item)

    # Identifiers must match and only one record should exist.
    assert product_id_1 == product_id_2

    cursor = in_memory_repo.conn.cursor()
    cursor.execute("SELECT * FROM products WHERE url = ?;", (initial_item.url,))
    rows = cursor.fetchall()
    assert len(rows) == 1
    record = rows[0]
    assert record["upc"] == "abc123xyz789"
    assert record["category"] == "Science Fiction"
    assert record["description"] == "A book description discovered on product detail page."


def test_price_snapshot_append(in_memory_repo: TrackerRepository):
    """Verify that multiple observations over time append snapshots for the same product."""
    run_1 = in_memory_repo.start_scrape_run("fast")
    run_2 = in_memory_repo.start_scrape_run("fast")

    item_day1 = ScrapedItem(
        title="Volatile Price Book",
        url="https://books.toscrape.com/catalogue/volatile_1/index.html",
        price_gbp=50.00,
        rating=4,
    )
    item_day2 = ScrapedItem(
        title="Volatile Price Book",
        url="https://books.toscrape.com/catalogue/volatile_1/index.html",
        price_gbp=40.00,
        rating=4,
    )

    in_memory_repo.record_batch(run_1, [item_day1])
    in_memory_repo.record_batch(run_2, [item_day2])

    cursor = in_memory_repo.conn.cursor()
    cursor.execute("SELECT id FROM products WHERE url = ?;", (item_day1.url,))
    product = cursor.fetchone()
    assert product is not None

    cursor.execute(
        "SELECT price_gbp, run_id FROM price_snapshots WHERE product_id = ? ORDER BY id ASC;",
        (product["id"],),
    )
    snapshots = cursor.fetchall()
    assert len(snapshots) == 2
    assert snapshots[0]["price_gbp"] == 50.00
    assert snapshots[0]["run_id"] == run_1
    assert snapshots[1]["price_gbp"] == 40.00
    assert snapshots[1]["run_id"] == run_2


def test_atomic_batch_rollback(in_memory_repo: TrackerRepository):
    """Verify that a batch failure rolls back all records in that transaction."""
    run_id = in_memory_repo.start_scrape_run("fast")

    valid_item = ScrapedItem(
        title="Valid Book",
        url="https://books.toscrape.com/catalogue/valid_1/index.html",
        price_gbp=12.50,
    )

    # Subclass with an invalid rating to trigger an SQLite CHECK constraint violation.
    class CorruptedItem(ScrapedItem):
        pass

    corrupted = CorruptedItem.model_construct(
        title="Corrupted Book",
        url="https://books.toscrape.com/catalogue/corrupted_1/index.html",
        price_gbp=10.0,
        rating=99,  # Violates CHECK(rating BETWEEN 1 AND 5)
        currency="GBP",
        in_stock=True,
    )

    with pytest.raises(sqlite3.IntegrityError):
        in_memory_repo.record_batch(run_id, [valid_item, corrupted])

    # Neither product nor snapshot from the batch should remain.
    cursor = in_memory_repo.conn.cursor()
    cursor.execute("SELECT COUNT(*) AS total FROM products;")
    assert cursor.fetchone()["total"] == 0

    cursor.execute("SELECT COUNT(*) AS total FROM price_snapshots;")
    assert cursor.fetchone()["total"] == 0
