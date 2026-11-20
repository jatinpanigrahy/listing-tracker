"""Integration tests for the command-line interface and argument handling."""

import subprocess
import sys
from pathlib import Path
import pandas as pd
import pytest

from src.cli import build_argument_parser, run_pipeline
from src.models import ScrapedItem
from src.storage.repository import TrackerRepository


def test_cli_help():
    """Verify that --help exits with code 0 and displays usage information."""
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage: listing-tracker" in result.stdout
    assert "--mode" in result.stdout
    assert "--export-csv" in result.stdout


def test_cli_invalid_args():
    """Verify that unrecognized flags cause argparse to exit with code 2."""
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "--non-existent-flag"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr.lower() or "error" in result.stderr.lower()


def test_cli_export_only(tmp_path: Path):
    """Verify that --export-only exports CSVs from existing SQLite DB without making HTTP calls."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "tracker.db"

    # Pre-populate database with a sample item.
    repo = TrackerRepository(db_path)
    run_id = repo.start_scrape_run("fast")
    repo.record_batch(
        run_id,
        [
            ScrapedItem(
                title="CLI Test Book",
                url="https://books.toscrape.com/catalogue/cli_test_1/index.html",
                price_gbp=30.00,
                rating=5,
            )
        ],
    )
    repo.complete_scrape_run(run_id, "SUCCESS", 1, 1)
    repo.close()

    # Invoke CLI with --export-only pointing to temporary data directory.
    parser = build_argument_parser()
    args = parser.parse_args(["--export-only", "--output-dir", str(data_dir)])
    exit_code = run_pipeline(args)

    assert exit_code == 0
    latest_csv = data_dir / "latest_listings.csv"
    history_csv = data_dir / "price_history.csv"

    assert latest_csv.exists()
    assert history_csv.exists()

    df_latest = pd.read_csv(latest_csv)
    assert len(df_latest) == 1
    assert df_latest.iloc[0]["title"] == "CLI Test Book"


def test_cli_invalid_pages():
    """Verify that non-positive page count returns usage error code 2."""
    parser = build_argument_parser()
    args = parser.parse_args(["--pages", "0"])
    exit_code = run_pipeline(args)
    assert exit_code == 2
