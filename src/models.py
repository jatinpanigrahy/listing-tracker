"""Domain models and runtime validation schemas.

Pydantic models here enforce data contracts at system boundaries: raw parsed
HTML structures from scrapers, canonical product records, point-in-time price
observations, and execution metadata for scrape runs.
"""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Return the current timestamp in UTC timezone."""
    return datetime.now(timezone.utc)


class ScrapedItem(BaseModel):
    """Raw structured record extracted from a listing or detail page."""

    title: str = Field(..., min_length=1, description="Book title")
    url: str = Field(..., description="Absolute URL to the product page")
    thumbnail_url: Optional[str] = Field(None, description="Absolute URL to product thumbnail image")
    price_gbp: float = Field(..., ge=0.0, description="Price in GBP")
    currency: str = Field(default="GBP", description="Currency 3-letter ISO code")
    rating: Optional[int] = Field(None, ge=1, le=5, description="Star rating 1 to 5")
    in_stock: bool = Field(default=True, description="Stock availability flag")
    stock_quantity: Optional[int] = Field(None, ge=0, description="Numerical units available")
    upc: Optional[str] = Field(None, description="Universal Product Code / unique SKU")
    category: Optional[str] = Field(None, description="Genre or category name")
    description: Optional[str] = Field(None, description="Product summary description")
    catalog_page: int = Field(default=1, ge=1, description="Catalog page where item was observed")


class Product(BaseModel):
    """Canonical catalog product stored in SQLite."""

    id: Optional[int] = None
    upc: Optional[str] = None
    title: str
    url: str
    thumbnail_url: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class PriceSnapshot(BaseModel):
    """Point-in-time observation of product pricing and stock availability."""

    id: Optional[int] = None
    run_id: int
    product_id: int
    price_gbp: float
    currency: str = "GBP"
    rating: Optional[int] = None
    in_stock: bool = True
    stock_quantity: Optional[int] = None
    scraped_at: datetime = Field(default_factory=_utc_now)


class ScrapeRun(BaseModel):
    """Execution metadata record tracking crawl progress and outcome."""

    id: Optional[int] = None
    started_at: datetime = Field(default_factory=_utc_now)
    completed_at: Optional[datetime] = None
    mode: str = Field(..., description="'fast' or 'deep'")
    pages_scraped: int = 0
    items_scraped: int = 0
    status: str = Field(default="RUNNING", description="'RUNNING', 'SUCCESS', 'FAILED'")
    error_message: Optional[str] = None
