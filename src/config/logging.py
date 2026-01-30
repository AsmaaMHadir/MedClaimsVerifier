"""
Structured Logging Configuration
Sets up loguru with console and file output
"""

import sys
from pathlib import Path
from loguru import logger


def setup_logging(log_level: str = "INFO", log_dir: str = "logs") -> None:
    """
    Configure structured logging with console and file output.

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR)
        log_dir: Directory for log files
    """
    # Remove default handler
    logger.remove()

    # Console output (structured, colorized)
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
        colorize=True,
    )

    # Ensure log directory exists
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # File output with rotation
    logger.add(
        log_path / "medverify_{time:YYYY-MM-DD}.log",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="100 MB",
        retention="7 days",
        compression="gz",
        enqueue=True,  # Thread-safe
    )

    # Separate error log
    logger.add(
        log_path / "medverify_errors_{time:YYYY-MM-DD}.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="50 MB",
        retention="30 days",
        compression="gz",
        enqueue=True,
    )

    logger.info(f"Logging initialized at {log_level} level")


def get_logger(name: str = __name__):
    """Get a logger instance with the given name."""
    return logger.bind(name=name)
