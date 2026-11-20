"""Scraper engine package for catalog extraction and detail page parsing."""

from src.scrapers.base import BaseScraper
from src.scrapers.books_toscrape import BooksToScrapeScraper

__all__ = ["BaseScraper", "BooksToScrapeScraper"]
