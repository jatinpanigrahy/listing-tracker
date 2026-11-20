"""Command-line interface and pipeline orchestrator for the price tracker.

Manages the complete lifecycle: parsing arguments, setting up graceful termination
signals, executing catalog crawls, committing database transactions, and triggering
analytical CSV exports.
"""

import argparse
import signal
import sys
import time
from pathlib import Path
from typing import List, Optional

from src.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_DELAY_SECONDS,
)
from src.logger import setup_logger
from src.scrapers.books_toscrape import BooksToScrapeScraper
from src.storage.exporter import DataExporter
from src.storage.repository import TrackerRepository

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_SIGINT = 130


def build_argument_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser with supported options and flags."""
    parser = argparse.ArgumentParser(
        prog="listing-tracker",
        description="Scrapes product listings, tracks price history in SQLite, and exports CSV analytics.",
    )

    parser.add_argument(
        "--mode",
        choices=["fast", "deep"],
        default="fast",
        help="Scrape mode: 'fast' extracts listing cards; 'deep' crawls product detail pages.",
    )

    parser.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Maximum number of catalog pages to scrape (1 to 50). Omit to scrape all available pages.",
    )

    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Filter scraping to a specific category slug (e.g. 'travel', 'mystery').",
    )

    parser.add_argument(
        "--export-csv",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Whether to export CSV snapshots upon scrape completion (default: true).",
    )
    parser.add_argument(
        "--no-export",
        dest="export_csv",
        action="store_false",
        help="Disable CSV export upon scrape completion.",
    )

    parser.add_argument(
        "--export-only",
        action="store_true",
        default=False,
        help="Skip scraping and regenerate CSV exports from the existing SQLite database.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Directory where SQLite database and exported CSVs are written (default: ./data).",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help="Sleep duration in seconds between HTTP requests to respect target rate limits.",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging verbosity level (default: INFO).",
    )

    return parser


def setup_signal_handlers(
    repo: TrackerRepository,
    active_run_id_box: List[Optional[int]],
    logger,
) -> None:
    """Register signal handlers to gracefully mark active runs as interrupted on SIGINT/SIGTERM."""

    def handle_signal(signum, frame):
        logger.warning("Interruption signal %s received. Performing graceful shutdown.", signum)
        active_id = active_run_id_box[0]
        if active_id is not None:
            try:
                repo.complete_scrape_run(
                    run_id=active_id,
                    status="FAILED",
                    pages_scraped=0,
                    items_scraped=0,
                    error_message="Execution interrupted by SIGINT / User",
                )
                logger.info("Marked active run #%d as FAILED.", active_id)
            except Exception as exc:
                logger.error("Failed to update run status during shutdown: %s", exc)
        sys.exit(EXIT_SIGINT)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)


def run_pipeline(args: argparse.Namespace) -> int:
    """Execute scraping and export pipeline matching parsed CLI options."""
    logger = setup_logger("cli", level=args.log_level)

    # Validate pages flag if specified.
    if args.pages is not None and args.pages < 1:
        logger.error("--pages must be an integer greater than or equal to 1.")
        return EXIT_USAGE

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "tracker.db"

    # Offline export mode skips network activity entirely.
    if args.export_only:
        logger.info("Export-only mode selected. Reading from %s...", db_path)
        if not db_path.exists():
            logger.warning("Database %s does not exist yet. Initializing empty schema before export.", db_path)
        exporter = DataExporter(db_path)
        try:
            latest_path, history_path = exporter.export_all(output_dir)
            logger.info("CSVs exported to %s and %s", latest_path, history_path)
            return EXIT_SUCCESS
        finally:
            exporter.close()

    # Active scraping run setup.
    repo = TrackerRepository(db_path)
    active_run_id_box: List[Optional[int]] = [None]
    setup_signal_handlers(repo, active_run_id_box, logger)

    start_time = time.time()
    run_id = repo.start_scrape_run(mode=args.mode)
    active_run_id_box[0] = run_id
    logger.info("Started scrape run #%d in '%s' mode (max_pages: %s)", run_id, args.mode, args.pages)

    scraper = BooksToScrapeScraper(delay_seconds=args.delay)
    pages_scraped = 0
    items_scraped = 0

    try:
        deep_mode = args.mode == "deep"
        for batch in scraper.scrape(max_pages=args.pages, deep=deep_mode, category=args.category):
            committed = repo.record_batch(run_id, batch)
            pages_scraped += 1
            items_scraped += committed
            logger.info(
                "Page %d committed (%d items in batch, %d total items).",
                pages_scraped,
                committed,
                items_scraped,
            )

        repo.complete_scrape_run(
            run_id=run_id,
            status="SUCCESS",
            pages_scraped=pages_scraped,
            items_scraped=items_scraped,
        )
        active_run_id_box[0] = None

        elapsed = time.time() - start_time
        logger.info(
            "Scrape run #%d finished in %.2fs: %d pages, %d items persisted.",
            run_id,
            elapsed,
            pages_scraped,
            items_scraped,
        )

        if args.export_csv:
            logger.info("Generating CSV exports in %s...", output_dir)
            exporter = DataExporter(repo.conn)
            latest_path, history_path = exporter.export_all(output_dir)
            logger.info("Exports written: %s, %s", latest_path, history_path)

        return EXIT_SUCCESS

    except Exception as exc:
        elapsed = time.time() - start_time
        logger.error("Scrape run #%d failed after %.2fs: %s", run_id, elapsed, exc, exc_info=True)
        repo.complete_scrape_run(
            run_id=run_id,
            status="FAILED",
            pages_scraped=pages_scraped,
            items_scraped=items_scraped,
            error_message=str(exc),
        )
        active_run_id_box[0] = None
        return EXIT_FAILURE

    finally:
        repo.close()


def main() -> None:
    """CLI script entrypoint."""
    parser = build_argument_parser()
    args = parser.parse_args()
    exit_code = run_pipeline(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
