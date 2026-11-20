"""HTTP networking utilities and HTML string normalization helpers.

Configures connection pooling and exponential retry policies for requests,
and provides sanitizers for extracting prices, star ratings, and stock counts
from raw DOM text nodes.
"""

import re
from typing import List, Optional, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from src.config import USER_AGENT

# Mapping textual star-rating class names to 1-5 integer equivalents.
STAR_RATING_MAP = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
}


def create_resilient_session(
    retries: int = 3,
    backoff_factor: float = 1.0,
    status_forcelist: Tuple[int, ...] = (429, 500, 502, 503, 504),
    user_agent: str = USER_AGENT,
) -> requests.Session:
    """Create a configured requests.Session with connection retries and politeness headers.

    Retries transient 5xx server errors and 429 rate limits with exponential backoff
    while reusing TCP connections across consecutive page fetches.
    """
    session = requests.Session()

    retry_strategy = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
    )

    return session


def clean_price(price_str: str) -> float:
    """Extract a floating-point numeric value from a currency-formatted string.

    Handles symbol prefixes such as '£51.77', '€12.50', or '$9.99'. Returns 0.0
    if no numerical characters are found.
    """
    if not price_str:
        return 0.0
    match = re.search(r"[\d]+\.?[\d]*", price_str.strip())
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return 0.0
    return 0.0


def parse_star_rating(class_names: List[str]) -> Optional[int]:
    """Extract the star rating integer (1-5) from CSS class names.

    Books.toscrape encodes ratings in classes like ['star-rating', 'Three'].
    Returns None if no matching rating word is found.
    """
    for cls in class_names:
        cleaned = cls.strip().lower()
        if cleaned in STAR_RATING_MAP:
            return STAR_RATING_MAP[cleaned]
    return None


def parse_stock_quantity(text: str) -> int:
    """Parse available numerical inventory count from availability strings.

    Extracts the digit group from patterns like 'In stock (22 available)'.
    Returns 0 when the string indicates out of stock or does not contain digits.
    """
    if not text:
        return 0

    lower = text.lower()
    if "out of stock" in lower:
        return 0

    match = re.search(r"\(?(\d+)\s*available\)?", lower)
    if match:
        return int(match.group(1))

    # Fallback to any standalone integer if specific phrase is absent.
    digits_match = re.search(r"\d+", text)
    if digits_match and "in stock" in lower:
        return int(digits_match.group(0))

    return 0
