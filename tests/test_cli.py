"""Integration tests for the command-line interface and argument handling."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import pytest

from src.cli import build_argument_parser, run_pipeline, setup_signal_handlers, EXIT_SIGINT
from src.logger import setup_logger
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


def test_cli_pipeline_success(tmp_path: Path):
    """Verify that running the pipeline end-to-end creates runs, commits batches, and writes CSVs."""
    data_dir = tmp_path / "run_data"
    parser = build_argument_parser()
    args = parser.parse_args(["--output-dir", str(data_dir), "--pages", "1"])

    sample_batch = [
        ScrapedItem(
            title="Mocked Book",
            url="https://books.toscrape.com/catalogue/mocked_1/index.html",
            price_gbp=15.99,
            rating=4,
        )
    ]

    with patch("src.cli.BooksToScrapeScraper.scrape", return_value=iter([sample_batch])):
        exit_code = run_pipeline(args)

    assert exit_code == 0
    assert (data_dir / "tracker.db").exists()
    assert (data_dir / "latest_listings.csv").exists()
    assert (data_dir / "price_history.csv").exists()

    repo = TrackerRepository(data_dir / "tracker.db")
    cursor = repo.conn.cursor()
    cursor.execute("SELECT status, items_scraped FROM scrape_runs ORDER BY id DESC LIMIT 1;")
    run = cursor.fetchone()
    assert run["status"] == "SUCCESS"
    assert run["items_scraped"] == 1
    repo.close()


def test_cli_pipeline_failure(tmp_path: Path):
    """Verify that a pipeline exception sets run status to FAILED and exits with 1."""
    data_dir = tmp_path / "fail_data"
    parser = build_argument_parser()
    args = parser.parse_args(["--output-dir", str(data_dir)])

    with patch("src.cli.BooksToScrapeScraper.scrape", side_effect=RuntimeError("Simulated network drop")):
        exit_code = run_pipeline(args)

    assert exit_code == 1
    repo = TrackerRepository(data_dir / "tracker.db")
    cursor = repo.conn.cursor()
    cursor.execute("SELECT status, error_message FROM scrape_runs ORDER BY id DESC LIMIT 1;")
    run = cursor.fetchone()
    assert run["status"] == "FAILED"
    assert "Simulated network drop" in run["error_message"]
    repo.close()


def test_cli_signal_handler(in_memory_repo: TrackerRepository):
    """Verify that the signal handler updates active run to FAILED and exits with code 130."""
    logger = setup_logger("test.sig")
    run_id = in_memory_repo.start_scrape_run("fast")
    active_box = [run_id]

    with patch("signal.signal") as mock_signal:
        setup_signal_handlers(in_memory_repo, active_box, logger)
        # Extract registered handler function
        registered_handler = mock_signal.call_args[0][1]

    with pytest.raises(SystemExit) as exc_info:
        registered_handler(2, None)

    assert exc_info.value.code == EXIT_SIGINT

    cursor = in_memory_repo.conn.cursor()
    cursor.execute("SELECT status, error_message FROM scrape_runs WHERE id = ?;", (run_id,))
    row = cursor.fetchone()
    assert row["status"] == "FAILED"
    assert "SIGINT" in row["error_message"]
