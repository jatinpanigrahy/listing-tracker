# Listing & Price Tracker

A Python CLI tool that tracks product prices and inventory over time from web catalogs. It crawls listing cards and detail pages, stores point-in-time snapshots in a local SQLite database, and exports structured CSV reports with computed price deltas and historical extrema.

The default scraper targets [books.toscrape.com](https://books.toscrape.com/), a sandbox bookstore catalog of 1,000 books across 50 pages.

---

## What It Produces

Every scrape run records timestamped observations to SQLite and can generate two analytical CSV files in `./data`:

1. **`latest_listings.csv`**: One row per unique product containing the most recently observed price, availability, star rating, and catalog metadata.
2. **`price_history.csv`**: A time-series log of all observations across runs, enriched with rolling calculations:
   - `prev_price_gbp`: Price on the immediate prior crawl.
   - `price_change_gbp`: Nominal change (`price_gbp - prev_price_gbp`).
   - `price_change_pct`: Percentage change relative to the prior price.
   - `all_time_min_price` and `all_time_max_price`: Historical boundaries for that product.

All CSV exports write to temporary `.tmp` files first and rename atomically, preventing corrupted or empty files if a process is interrupted.

---

## Architecture Overview

```
                      ┌────────────────────────┐
                      │ books.toscrape.com     │
                      └───────────┬────────────┘
                                  │ HTTP / BeautifulSoup
                                  ▼
                      ┌────────────────────────┐
                      │ Scraper Engine         │
                      │ (BaseScraper / Books)  │
                      └───────────┬────────────┘
                                  │ Pydantic Validation
                                  ▼
                      ┌────────────────────────┐
                      │ SQLite Store (WAL)     │
                      │ (Runs, Products, Snaps)│
                      └───────────┬────────────┘
                                  │ SQL / Window Functions
                                  ▼
                      ┌────────────────────────┐
                      │ Pandas Exporter        │
                      │ - latest_listings.csv  │
                      │ - price_history.csv    │
                      └────────────────────────┘
```

The system separates concerns across four distinct layers:
- **`src/scrapers/`**: Abstract crawler interface (`BaseScraper`) with connection pooling, exponential retry backoff, and BeautifulSoup DOM extraction.
- **`src/models.py`**: Pydantic v2 schemas validating raw scraped fields, product identities, and snapshot data.
- **`src/storage/`**: SQLite persistence configured with Write-Ahead Logging (`WAL`), atomic transactions per page batch, and idempotent product upserts.
- **`src/cli.py`**: Command-line entrypoint with graceful signal trapping (`SIGINT`/`SIGTERM`) and offline export flags.

---

## Requirements

- Python 3.10 or newer
- Virtual environment recommended

---

## Installation

```bash
# Clone the repository
git clone https://github.com/jatinpanigrahy/listing-tracker.git
cd listing-tracker

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install package and testing dependencies in editable mode
pip install -e ".[dev]"
```

---

## Usage

### Quick Test Crawl

Scrape only the first 2 catalog pages in fast mode (card listings only):

```bash
python -m src.cli --pages 2
```

### Full Fast Crawl

Crawl all 50 catalog pages (~1,000 items) and export refreshed CSV files:

```bash
python -m src.cli --mode fast
```

### Deep Crawl

Visit individual product pages to extract UPC codes, exact inventory quantities, genre breadcrumbs, and descriptions:

```bash
python -m src.cli --mode deep --pages 3 --delay 0.5
```

### Offline Export Mode

Regenerate CSV summaries from the existing database without making network requests:

```bash
python -m src.cli --export-only
```

### CLI Flag Reference

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--mode {fast,deep}` | `fast` | `fast` reads listing cards only. `deep` visits individual product detail pages. |
| `--pages N` | `None` (all) | Maximum number of catalog pages to scrape (1 to 50). |
| `--category SLUG` | `None` | Filter crawl to a specific category (e.g. `travel`, `mystery`). |
| `--export-csv` / `--no-export` | `True` | Whether to write updated CSV files upon run completion. |
| `--export-only` | `False` | Regenerate CSV files from the local database without making HTTP calls. |
| `--output-dir PATH` | `./data` | Directory where SQLite database and CSV files are stored. |
| `--delay SECONDS` | `0.5` | Sleep delay between consecutive HTTP requests. |
| `--log-level LEVEL` | `INFO` | Console logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

---

## Automated Scheduling with GitHub Actions

The workflow file [`.github/workflows/tracker.yml`](file:///.github/workflows/tracker.yml) schedules daily scrapes at 06:00 UTC using GitHub-hosted runners. It executes the CLI, commits updated CSV reports and the database back to the repository, and uploads a 30-day artifact backup.

Manual trigger is also supported via GitHub's `workflow_dispatch` with custom page and mode inputs.

---

## Test Suite

The test suite runs with zero network dependencies. All parser tests use static HTML snapshots in `tests/fixtures/`, and storage tests use an in-memory SQLite database.

```bash
# Run all tests
pytest tests/ -v

# Run with test coverage
pytest --cov=src tests/ --cov-report=term-missing
```

---

## Known Limits & Considerations

- **Single Scraper Target**: `BooksToScrapeScraper` is tailored to `books.toscrape.com`. New targets can be added by implementing `BaseScraper`.
- **Database Locks**: SQLite handles single-writer concurrency. For distributed multi-node workers, migrate the repository layer to PostgreSQL.
- **Deep Scrape Duration**: A full deep crawl of 1,000 books with a 0.5s polite delay takes ~8 to 10 minutes. Use `--pages` when running quick exploratory audits.
