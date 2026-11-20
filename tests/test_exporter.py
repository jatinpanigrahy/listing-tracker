"""Unit tests for the analytical CSV exporter and price delta calculations."""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.models import ScrapedItem
from src.storage.exporter import DataExporter
from src.storage.repository import TrackerRepository


def test_export_latest_listings_csv(in_memory_repo: TrackerRepository, tmp_path: Path):
    """Verify that latest listings CSV outputs only the most recent snapshot per product."""
    run_1 = in_memory_repo.start_scrape_run("fast")
    item_old = ScrapedItem(
        title="Book One",
        url="https://books.toscrape.com/catalogue/book_1/index.html",
        price_gbp=20.00,
        rating=2,
    )
    in_memory_repo.record_batch(run_1, [item_old])

    run_2 = in_memory_repo.start_scrape_run("fast")
    item_new = ScrapedItem(
        title="Book One",
        url="https://books.toscrape.com/catalogue/book_1/index.html",
        price_gbp=25.00,
        rating=4,
    )
    in_memory_repo.record_batch(run_2, [item_new])

    exporter = DataExporter(in_memory_repo.conn)
    output_path = tmp_path / "latest_listings.csv"
    result_path = exporter.export_latest_listings(output_path)

    assert result_path.exists()
    df = pd.read_csv(result_path)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["title"] == "Book One"
    assert row["current_price_gbp"] == 25.00
    assert row["rating"] == 4
    expected_cols = [
        "product_id",
        "upc",
        "title",
        "category",
        "current_price_gbp",
        "rating",
        "in_stock",
        "stock_quantity",
        "product_url",
        "last_scraped_at",
    ]
    for col in expected_cols:
        assert col in df.columns


def test_export_price_history_deltas(in_memory_repo: TrackerRepository, tmp_path: Path):
    """Verify temporal price difference and percentage shift calculations across multiple runs."""
    run_1 = in_memory_repo.start_scrape_run("fast")
    run_2 = in_memory_repo.start_scrape_run("fast")
    run_3 = in_memory_repo.start_scrape_run("fast")

    url = "https://books.toscrape.com/catalogue/trend_book/index.html"
    item_1 = ScrapedItem(title="Trend Book", url=url, price_gbp=100.00)
    item_2 = ScrapedItem(title="Trend Book", url=url, price_gbp=80.00)
    item_3 = ScrapedItem(title="Trend Book", url=url, price_gbp=120.00)

    in_memory_repo.record_batch(run_1, [item_1])
    in_memory_repo.record_batch(run_2, [item_2])
    in_memory_repo.record_batch(run_3, [item_3])

    exporter = DataExporter(in_memory_repo.conn)
    output_path = tmp_path / "price_history.csv"
    exporter.export_price_history(output_path)

    df = pd.read_csv(output_path)
    assert len(df) == 3

    # Run 1: Baseline observation without previous reference.
    r1 = df.iloc[0]
    assert r1["price_gbp"] == 100.00
    assert pd.isna(r1["prev_price_gbp"])
    assert pd.isna(r1["price_change_gbp"])
    assert pd.isna(r1["price_change_pct"])

    # Run 2: £100 -> £80 (drop of £20, -20.0%).
    r2 = df.iloc[1]
    assert r2["price_gbp"] == 80.00
    assert r2["prev_price_gbp"] == 100.00
    assert r2["price_change_gbp"] == -20.00
    assert r2["price_change_pct"] == -20.00

    # Run 3: £80 -> £120 (increase of £40, +50.0%).
    r3 = df.iloc[2]
    assert r3["price_gbp"] == 120.00
    assert r3["prev_price_gbp"] == 80.00
    assert r3["price_change_gbp"] == 40.00
    assert r3["price_change_pct"] == 50.00


def test_export_extrema_calculations(in_memory_repo: TrackerRepository, tmp_path: Path):
    """Verify that all-time high and low prices are computed across all product observations."""
    runs = [in_memory_repo.start_scrape_run("fast") for _ in range(3)]
    url = "https://books.toscrape.com/catalogue/extrema_book/index.html"
    prices = [100.00, 75.00, 90.00]

    for run_id, price in zip(runs, prices):
        in_memory_repo.record_batch(run_id, [ScrapedItem(title="Extrema Book", url=url, price_gbp=price)])

    exporter = DataExporter(in_memory_repo.conn)
    output_path = tmp_path / "price_history.csv"
    exporter.export_price_history(output_path)

    df = pd.read_csv(output_path)
    assert len(df) == 3

    # All rows for this product should report the global min and max.
    for _, row in df.iterrows():
        assert row["all_time_min_price"] == 75.00
        assert row["all_time_max_price"] == 100.00


def test_atomic_file_replacement(in_memory_repo: TrackerRepository, tmp_path: Path):
    """Verify that exports write to temporary files first and leave no orphaned .tmp files."""
    run_id = in_memory_repo.start_scrape_run("fast")
    in_memory_repo.record_batch(
        run_id,
        [ScrapedItem(title="Atomic Test", url="https://books.toscrape.com/item", price_gbp=9.99)],
    )

    exporter = DataExporter(in_memory_repo.conn)
    output_path = tmp_path / "clean_export.csv"
    exporter.export_latest_listings(output_path)

    # Primary CSV should exist, and sibling temporary file should be cleaned up.
    assert output_path.exists()
    assert not output_path.with_suffix(".tmp").exists()
