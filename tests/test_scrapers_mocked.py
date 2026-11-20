"""Mocked network and pagination tests for the scraping engine."""

from unittest.mock import MagicMock
import responses
import pytest

from src.scrapers.books_toscrape import BooksToScrapeScraper
from src.scrapers.utils import create_resilient_session


def test_create_resilient_session():
    """Verify that the resilient HTTP session sets up adapters and headers."""
    session = create_resilient_session(retries=2, backoff_factor=0.5)
    assert "PriceTrackerBot" in session.headers["User-Agent"]
    assert "http://" in session.adapters
    assert "https://" in session.adapters


def test_build_page_url():
    """Verify URL construction for root catalogue and category filters."""
    scraper = BooksToScrapeScraper(delay_seconds=0.0)
    root_url = scraper.build_page_url(1)
    assert root_url == "https://books.toscrape.com/catalogue/page-1.html"

    cat_url = scraper.build_page_url(2, category="mystery_3")
    assert cat_url == "https://books.toscrape.com/catalogue/category/books/mystery_3/page-2.html"


def test_get_listing_urls():
    """Verify generation of page URL lists up to the specified ceiling."""
    scraper = BooksToScrapeScraper(delay_seconds=0.0)
    urls = scraper.get_listing_urls(max_pages=3)
    assert len(urls) == 3
    assert urls[0] == "https://books.toscrape.com/catalogue/page-1.html"
    assert urls[2] == "https://books.toscrape.com/catalogue/page-3.html"


@responses.activate
def test_scrape_stops_on_404(sample_listing_html: str):
    """Verify that an HTTP 404 cleanly halts pagination without throwing an unhandled error."""
    scraper = BooksToScrapeScraper(delay_seconds=0.0)

    # Page 1 succeeds, Page 2 returns 404 (end of catalog).
    responses.add(
        responses.GET,
        "https://books.toscrape.com/catalogue/page-1.html",
        body=sample_listing_html,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://books.toscrape.com/catalogue/page-2.html",
        status=404,
    )

    batches = list(scraper.scrape(max_pages=5))
    assert len(batches) == 1
    assert len(batches[0]) == 2


@responses.activate
def test_scrape_deep_mode(sample_listing_html: str, sample_detail_html: str):
    """Verify that deep mode fetches individual product detail pages and enriches items."""
    scraper = BooksToScrapeScraper(delay_seconds=0.0)

    responses.add(
        responses.GET,
        "https://books.toscrape.com/catalogue/page-1.html",
        body=sample_listing_html,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        body=sample_detail_html,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html",
        body=sample_detail_html,
        status=200,
    )

    batches = list(scraper.scrape(max_pages=1, deep=True))
    assert len(batches) == 1
    items = batches[0]
    assert items[0].upc == "a897fe39b1053632"
    assert items[0].category == "Poetry"
    assert items[0].stock_quantity == 22
