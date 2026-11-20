"""Analytical data exporter transforming SQLite time-series snapshots into CSV files.

Computes rolling price differences, percentage changes, and historical minimum/maximum
extrema across product observations, saving outputs atomically to prevent partial writes.
"""

from pathlib import Path
import sqlite3
from typing import Tuple, Union
import pandas as pd

from src.logger import setup_logger
from src.storage.database import DatabaseManager

logger = setup_logger("storage.exporter")


class DataExporter:
    """Exports structured catalog listings and price history analytics to CSV."""

    def __init__(self, db_source: Union[DatabaseManager, sqlite3.Connection, Path, str]):
        if isinstance(db_source, sqlite3.Connection):
            self.conn = db_source
            self._owns_connection = False
        elif isinstance(db_source, DatabaseManager):
            self.conn = db_source.get_connection()
            self._owns_connection = True
        else:
            self.conn = DatabaseManager(db_source).get_connection()
            self._owns_connection = True

    def close(self) -> None:
        """Close connection if owned by this exporter instance."""
        if self._owns_connection and self.conn:
            self.conn.close()

    def export_latest_listings(self, output_path: Union[Path, str]) -> Path:
        """Query the single latest snapshot for every canonical product and write to CSV.

        Columns: product_id, upc, title, category, current_price_gbp, rating,
        in_stock, stock_quantity, product_url, last_scraped_at.
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        query = """
        SELECT 
            p.id AS product_id,
            p.upc,
            p.title,
            p.category,
            s.price_gbp AS current_price_gbp,
            s.rating,
            s.in_stock,
            s.stock_quantity,
            p.url AS product_url,
            s.scraped_at AS last_scraped_at
        FROM products p
        JOIN price_snapshots s ON s.product_id = p.id
        WHERE s.id = (
            SELECT s2.id 
            FROM price_snapshots s2 
            WHERE s2.product_id = p.id 
            ORDER BY s2.scraped_at DESC, s2.id DESC 
            LIMIT 1
        )
        ORDER BY p.id ASC;
        """

        df = pd.read_sql_query(query, self.conn)

        # Atomic file write using a temporary sibling file.
        temp_file = output_file.with_suffix(".tmp")
        df.to_csv(temp_file, index=False, encoding="utf-8")
        temp_file.replace(output_file)

        logger.info("Exported %d current listings to %s", len(df), output_file)
        return output_file

    def export_price_history(self, output_path: Union[Path, str]) -> Path:
        """Compute rolling price deltas and extrema across historical snapshots.

        Generates time-series CSV enriched with previous price, nominal difference,
        percentage shift, and all-time high/low benchmarks.
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        query = """
        SELECT 
            s.id AS snapshot_id,
            s.run_id,
            s.product_id,
            p.title,
            p.upc,
            p.category,
            s.price_gbp,
            s.currency,
            s.rating,
            s.in_stock,
            s.stock_quantity,
            s.scraped_at
        FROM price_snapshots s
        JOIN products p ON s.product_id = p.id
        ORDER BY s.product_id ASC, s.scraped_at ASC, s.id ASC;
        """

        df = pd.read_sql_query(query, self.conn)

        if not df.empty:
            # Shift within each product group to locate immediate prior observation.
            df["prev_price_gbp"] = df.groupby("product_id")["price_gbp"].shift(1)
            df["price_change_gbp"] = (df["price_gbp"] - df["prev_price_gbp"]).round(2)
            df["price_change_pct"] = (
                ((df["price_gbp"] - df["prev_price_gbp"]) / df["prev_price_gbp"]) * 100
            ).round(2)

            # Historical min and max across all observations for the product.
            df["all_time_min_price"] = df.groupby("product_id")["price_gbp"].transform("min")
            df["all_time_max_price"] = df.groupby("product_id")["price_gbp"].transform("max")
        else:
            df["prev_price_gbp"] = pd.Series(dtype="float64")
            df["price_change_gbp"] = pd.Series(dtype="float64")
            df["price_change_pct"] = pd.Series(dtype="float64")
            df["all_time_min_price"] = pd.Series(dtype="float64")
            df["all_time_max_price"] = pd.Series(dtype="float64")

        # Explicit column ordering matching specification.
        desired_columns = [
            "snapshot_id",
            "run_id",
            "product_id",
            "title",
            "upc",
            "category",
            "price_gbp",
            "prev_price_gbp",
            "price_change_gbp",
            "price_change_pct",
            "all_time_min_price",
            "all_time_max_price",
            "rating",
            "in_stock",
            "stock_quantity",
            "scraped_at",
        ]
        df = df[[c for c in desired_columns if c in df.columns]]

        temp_file = output_file.with_suffix(".tmp")
        df.to_csv(temp_file, index=False, encoding="utf-8")
        temp_file.replace(output_file)

        logger.info("Exported %d price history records to %s", len(df), output_file)
        return output_file

    def export_all(
        self,
        output_dir: Union[Path, str],
        latest_filename: str = "latest_listings.csv",
        history_filename: str = "price_history.csv",
    ) -> Tuple[Path, Path]:
        """Convenience method exporting both latest listings and price history."""
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        latest_path = self.export_latest_listings(target_dir / latest_filename)
        history_path = self.export_price_history(target_dir / history_filename)
        return latest_path, history_path
