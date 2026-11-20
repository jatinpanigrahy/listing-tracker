"""Concrete scraper for the books.toscrape.com catalog.

Extracts listing cards, resolves relative URLs, parses star ratings, and enriches
items with deep attributes (UPC, genre breadcrumbs, stock counts) when requested.
"""

import re
import time
from typing import Generator, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests

from src.config import DEFAULT_DELAY_SECONDS, TARGET_BASE_URL
from src.logger import setup_logger
from src.models import ScrapedItem
from src.scrapers.base import BaseScraper
from src.scrapers.utils import (
    clean_price,
    create_resilient_session,
    parse_star_rating,
    parse_stock_quantity,
)

logger = setup_logger("scrapers.books")


class BooksToScrapeScraper(BaseScraper):
    """Scraper implementation targeting the books.toscrape.com catalog."""

    def __init__(
        self,
        delay_seconds: float = DEFAULT_DELAY_SECONDS,
        session: Optional[requests.Session] = None,
        base_url: str = TARGET_BASE_URL,
    ):
        super().__init__(delay_seconds=delay_seconds)
        self.base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self.session = session or create_resilient_session()

    def build_page_url(self, page_number: int, category: Optional[str] = None) -> str:
        """Construct the absolute URL for a catalog pagination index."""
        if category:
            # Handle category filtering URLs when category slug is specified.
            return urljoin(self.base_url, f"catalogue/category/books/{category}/page-{page_number}.html")
        return urljoin(self.base_url, f"catalogue/page-{page_number}.html")

    def get_listing_urls(
        self,
        max_pages: Optional[int] = None,
        category: Optional[str] = None,
    ) -> List[str]:
        """Generate candidate page URLs up to the specified page ceiling."""
        limit = max_pages if max_pages is not None else 50
        return [self.build_page_url(page_num, category) for page_num in range(1, limit + 1)]

    def parse_listing_page(self, html_content: str, page_url: str) -> List[ScrapedItem]:
        """Parse summary product cards from a catalog page."""
        soup = BeautifulSoup(html_content, "html.parser")
        product_pods = soup.select("article.product_pod")
        items: List[ScrapedItem] = []

        # Derive page number from the current URL for catalog tracking.
        page_match = re.search(r"page-(\d+)\.html", page_url)
        catalog_page = int(page_match.group(1)) if page_match else 1

        for pod in product_pods:
            # Extract title: prefer the full 'title' attribute on the link; fallback to visible text.
            title_tag = pod.select_one("h3 a")
            if not title_tag:
                continue

            title = title_tag.get("title") or title_tag.get_text(strip=True)
            relative_url = title_tag.get("href", "")
            absolute_url = urljoin(page_url, relative_url)

            # Extract thumbnail image.
            img_tag = pod.select_one(".image_container img")
            thumbnail_url = (
                urljoin(page_url, img_tag.get("src", "")) if img_tag and img_tag.get("src") else None
            )

            # Extract price.
            price_tag = pod.select_one(".product_price .price_color")
            price_str = price_tag.get_text(strip=True) if price_tag else ""
            price_gbp = clean_price(price_str)

            # Extract rating from class list (e.g. ['star-rating', 'Three']).
            rating_tag = pod.select_one("p.star-rating")
            rating = (
                parse_star_rating(rating_tag.get("class", [])) if rating_tag else None
            )

            # Check stock availability status flag.
            stock_tag = pod.select_one(".product_price .instock.availability")
            stock_text = stock_tag.get_text(strip=True) if stock_tag else ""
            in_stock = "in stock" in stock_text.lower()

            item = ScrapedItem(
                title=title,
                url=absolute_url,
                thumbnail_url=thumbnail_url,
                price_gbp=price_gbp,
                currency="GBP",
                rating=rating,
                in_stock=in_stock,
                catalog_page=catalog_page,
            )
            items.append(item)

        return items

    def parse_detail_page(self, html_content: str, item: ScrapedItem) -> ScrapedItem:
        """Enrich a ScrapedItem with deep attributes from its individual product page."""
        soup = BeautifulSoup(html_content, "html.parser")

        # Category extraction from breadcrumbs: Home > Books > [Category] > Title
        category = item.category
        breadcrumb_links = soup.select("ul.breadcrumb li a")
        if len(breadcrumb_links) >= 3:
            category = breadcrumb_links[2].get_text(strip=True)

        # Description extraction: <div id="product_description"><h2>...</h2></div><p>...</p>
        description = item.description
        desc_header = soup.select_one("#product_description")
        if desc_header:
            next_p = desc_header.find_next_sibling("p")
            if next_p:
                description = next_p.get_text(strip=True)

        # UPC and precise numerical stock from the specification table.
        upc = item.upc
        stock_quantity = item.stock_quantity

        info_rows = soup.select("table.table-striped tr")
        for row in info_rows:
            th = row.select_one("th")
            td = row.select_one("td")
            if not th or not td:
                continue

            header_name = th.get_text(strip=True).upper()
            cell_value = td.get_text(strip=True)

            if "UPC" in header_name:
                upc = cell_value
            elif "AVAILABILITY" in header_name:
                stock_quantity = parse_stock_quantity(cell_value)

        return item.model_copy(
            update={
                "upc": upc,
                "category": category,
                "description": description,
                "stock_quantity": stock_quantity,
            }
        )

    def scrape(
        self,
        max_pages: Optional[int] = None,
        deep: bool = False,
        category: Optional[str] = None,
    ) -> Generator[List[ScrapedItem], None, None]:
        """Execute the scrape loop yielding batches of items page by page."""
        page_num = 1
        limit = max_pages if max_pages is not None else 50

        while page_num <= limit:
            page_url = self.build_page_url(page_num, category)
            logger.info("Fetching catalog page %d: %s", page_num, page_url)

            try:
                response = self.session.get(page_url, timeout=15)
            except requests.RequestException as exc:
                logger.error("Network error on page %d: %s", page_num, exc)
                break

            # 404 indicates end of pagination on books.toscrape.com.
            if response.status_code == 404:
                logger.info("Reached end of catalog (404 received at page %d).", page_num)
                break

            if response.status_code != 200:
                logger.warning(
                    "Unexpected status code %d for %s. Stopping scrape.",
                    response.status_code,
                    page_url,
                )
                break

            items = self.parse_listing_page(response.text, page_url)
            if not items:
                logger.info("No items found on page %d. Stopping pagination.", page_num)
                break

            if deep:
                enriched_items: List[ScrapedItem] = []
                for item in items:
                    if self.delay_seconds > 0:
                        time.sleep(self.delay_seconds)
                    try:
                        detail_resp = self.session.get(item.url, timeout=15)
                        if detail_resp.status_code == 200:
                            enriched_items.append(self.parse_detail_page(detail_resp.text, item))
                        else:
                            enriched_items.append(item)
                    except requests.RequestException as exc:
                        logger.warning("Failed to fetch detail page for %s: %s", item.url, exc)
                        enriched_items.append(item)
                items = enriched_items

            yield items

            page_num += 1
            if self.delay_seconds > 0 and page_num <= limit:
                time.sleep(self.delay_seconds)
