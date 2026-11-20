"""Structured logging configuration for console and file output.

Formats log entries with timestamps, severity levels, module names, and line numbers
to simplify debugging during local runs and automated scheduler executions.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str = "tracker",
    level: str = "INFO",
    log_file: Optional[Path] = None,
) -> logging.Logger:
    """Configure and return a structured logger instance.

    Attaches a stream handler pointing to standard output and, when a file path
    is provided, a rotating file handler that caps disk usage at 5 MB per file
    with up to 3 backups. Avoids duplicating handlers if called multiple times.
    """
    logger = logging.getLogger(name)
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    # Return existing configuration if handlers are already set up.
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)8s] %(name)s: %(message)s (%(filename)s:%(lineno)d)"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)
    logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(numeric_level)
        logger.addHandler(file_handler)

    return logger
