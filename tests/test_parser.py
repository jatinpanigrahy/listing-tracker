"""Unit tests for HTML catalog parsing and string normalization helpers."""

from src.scrapers.books_toscrape import BooksToScrapeScraper
from src.scrapers.utils import clean_price, parse_star_rating, parse_stock_quantity


def test_parse_listing_page_count(scraper: BooksToScrapeScraper, sample_listing_html: str):
    """Verify that parsing returns the exact number of product cards present."""
    page_url = "https://books.toscrape.com/catalogue/page-1.html"
    items = scraper.parse_listing_page(sample_listing_html, page_url)
    assert len(items) == 2


def test_parse_listing_fields(scraper: BooksToScrapeScraper, sample_listing_html: str):
    """Verify field extraction, relative URL resolution, and type conversions."""
    page_url = "https://books.toscrape.com/catalogue/page-1.html"
    items = scraper.parse_listing_page(sample_listing_html, page_url)

    first = items[0]
    assert first.title == "A Light in the Attic"
    assert first.url == "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    assert first.thumbnail_url == "https://books.toscrape.com/media/cache/2c/da/2cdad67c44b002e7ead0cc35693c0e8b.jpg"
    assert first.price_gbp == 51.77
    assert first.currency == "GBP"
    assert first.rating == 3
    assert first.in_stock is True
    assert first.catalog_page == 1

    second = items[1]
    assert second.title == "Tipping the Velvet"
    assert second.price_gbp == 10.00
    assert second.rating == 1
    assert second.in_stock is False


def test_rating_parsing_all_values():
    """Verify mapping of textual rating classes to integers 1 through 5."""
    ratings = [
        parse_star_rating(["star-rating", word])
        for word in ["One", "Two", "Three", "Four", "Five"]
    ]
    assert ratings == [1, 2, 3, 4, 5]

    # Unknown or missing rating classes should resolve cleanly to None.
    assert parse_star_rating(["star-rating", "Unknown"]) is None
    assert parse_star_rating([]) is None


def test_currency_extraction():
    """Verify extraction of floating-point prices across different currency formats."""
    assert clean_price("£51.77") == 51.77
    assert clean_price("€12.50") == 12.50
    assert clean_price("$9.99") == 9.99
    assert clean_price("Free") == 0.0
    assert clean_price("") == 0.0


def test_stock_quantity_regex():
    """Verify extraction of inventory counts from availability strings."""
    assert parse_stock_quantity("In stock (22 available)") == 22
    assert parse_stock_quantity("In stock (1 available)") == 1
    assert parse_stock_quantity("Out of stock") == 0
    assert parse_stock_quantity("") == 0


def test_detail_page_enrichment(scraper: BooksToScrapeScraper, sample_listing_html: str, sample_detail_html: str):
    """Verify that detail page parsing populates UPC, category, stock count, and description."""
    page_url = "https://books.toscrape.com/catalogue/page-1.html"
    base_item = scraper.parse_listing_page(sample_listing_html, page_url)[0]

    enriched = scraper.parse_detail_page(sample_detail_html, base_item)
    assert enriched.upc == "a897fe39b1053632"
    assert enriched.category == "Poetry"
    assert enriched.stock_quantity == 22
    assert "classic collection of poems" in enriched.description
    # Base attributes must be preserved.
    assert enriched.title == "A Light in the Attic"
    assert enriched.price_gbp == 51.77
