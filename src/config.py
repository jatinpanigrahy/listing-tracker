"""Application configuration and environment defaults.

Paths, network timeouts, and request throttle rates are defined here with
environment variable overrides so test suites and containerized runners can
redirect outputs or adjust pacing without modifying code.
"""

import os
from pathlib import Path

# Base data directory where SQLite files and generated CSV reports reside.
DEFAULT_DATA_DIR: Path = Path(os.getenv("TRACKER_DATA_DIR", "./data"))

# Primary SQLite database file path.
DEFAULT_DB_PATH: Path = Path(os.getenv("TRACKER_DB_PATH", str(DEFAULT_DATA_DIR / "tracker.db")))

# Default export target for current product snapshots.
DEFAULT_LATEST_CSV_PATH: Path = DEFAULT_DATA_DIR / "latest_listings.csv"

# Default export target for complete price history and delta analytics.
DEFAULT_HISTORY_CSV_PATH: Path = DEFAULT_DATA_DIR / "price_history.csv"

# Throttle delay between HTTP requests in seconds to avoid overloading target servers.
DEFAULT_DELAY_SECONDS: float = float(os.getenv("TRACKER_DELAY", "0.5"))

# Socket connection and read timeout in seconds.
DEFAULT_TIMEOUT_SECONDS: int = int(os.getenv("TRACKER_TIMEOUT", "15"))

# Identifying User-Agent header sent with all outbound scraper requests.
USER_AGENT: str = "PriceTrackerBot/1.0 (+https://github.com/portfolio/listing-tracker)"

# Root URL for the books sandbox catalog.
TARGET_BASE_URL: str = "https://books.toscrape.com/"
