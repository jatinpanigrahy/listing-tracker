"""Unit tests for structured logger configuration and file rotation."""

import logging
from pathlib import Path

from src.logger import setup_logger


def test_setup_logger_console_only():
    """Verify logger creation with console stream handler."""
    logger = setup_logger("test.console", level="DEBUG")
    assert logger.name == "test.console"
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) >= 1
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)


def test_setup_logger_with_file(tmp_path: Path):
    """Verify that a rotating file handler is attached and creates the destination log file."""
    log_file = tmp_path / "logs" / "tracker_test.log"
    logger = setup_logger("test.file", level="INFO", log_file=log_file)

    logger.info("Test log message for file handler")

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Test log message for file handler" in content
    assert "[    INFO]" in content
