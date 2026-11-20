"""Shared pytest fixtures and test environment configuration."""

from pathlib import Path
import pytest

from src.scrapers.books_toscrape import BooksToScrapeScraper
from src.storage.repository import TrackerRepository

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_listing_html() -> str:
    """Load the sample catalog listing HTML fixture."""
    fixture_path = FIXTURES_DIR / "listing_page.html"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def sample_detail_html() -> str:
    """Load the sample product detail HTML fixture."""
    fixture_path = FIXTURES_DIR / "detail_page.html"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def in_memory_repo() -> TrackerRepository:
    """Provide an isolated in-memory SQLite repository for testing."""
    repo = TrackerRepository(db_path=Path(":memory:"))
    try:
        yield repo
    finally:
        repo.close()


@pytest.fixture
def scraper() -> BooksToScrapeScraper:
    """Provide a scraper instance configured with 0 delay for test runs."""
    return BooksToScrapeScraper(delay_seconds=0.0)
