"""Logging configuration for GeoLedger."""

import logging
import sys
from pathlib import Path


def setup_logging(log_level: str = "INFO", log_dir: str = "logs"):
    """Configure application-wide logging."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # File handler
    file_handler = logging.FileHandler(log_path / "geoldger.log", encoding="utf-8")
    file_handler.setFormatter(formatter)

    # Root logger
    root_logger = logging.getLogger("geoldger")
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    return root_logger


logger = setup_logging()
