"""Shared pytest fixtures and test environment configuration."""

from pathlib import Path
import pytest

from src.storage.repository import TrackerRepository

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_listing_html() -> str:
    """Load the sample catalog listing HTML fixture."""
    fixture_path = FIXTURES_DIR / "listing_page.html"
    if fixture_path.exists():
        with open(fixture_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


@pytest.fixture
def sample_detail_html() -> str:
    """Load the sample product detail HTML fixture."""
    fixture_path = FIXTURES_DIR / "detail_page.html"
    if fixture_path.exists():
        with open(fixture_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


@pytest.fixture
def in_memory_repo() -> TrackerRepository:
    """Provide an isolated in-memory SQLite repository for testing."""
    repo = TrackerRepository(db_path=Path(":memory:"))
    try:
        yield repo
    finally:
        repo.close()
