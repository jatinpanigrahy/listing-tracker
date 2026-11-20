"""Abstract scraper base contract.

Establishes the lifecycle methods every catalog scraper must implement: generating
catalog URLs, parsing summary cards, enriching items with detail page data, and
yielding streamed item batches.
"""

from abc import ABC, abstractmethod
from typing import Generator, List, Optional
from src.models import ScrapedItem


class BaseScraper(ABC):
    """Abstract interface defining the crawling and parsing contract."""

    def __init__(self, delay_seconds: float = 0.5):
        self.delay_seconds = delay_seconds

    @abstractmethod
    def get_listing_urls(self, max_pages: Optional[int] = None) -> List[str]:
        """Generate or discover the list of catalog page URLs to scrape."""
        pass

    @abstractmethod
    def parse_listing_page(self, html_content: str, page_url: str) -> List[ScrapedItem]:
        """Parse a catalog HTML page and extract a list of basic ScrapedItem instances."""
        pass

    @abstractmethod
    def parse_detail_page(self, html_content: str, item: ScrapedItem) -> ScrapedItem:
        """Enrich a ScrapedItem with deep attributes from its individual product page."""
        pass

    @abstractmethod
    def scrape(
        self,
        max_pages: Optional[int] = None,
        deep: bool = False,
    ) -> Generator[List[ScrapedItem], None, None]:
        """Execute the scraping pipeline yielding items page-by-page.

        Yields batches of items to enable streaming database persistence without
        buffering the entire catalog in memory.
        """
        pass
