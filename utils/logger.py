"""
Logging utility for Logiq
Configures structured logging with file and console output
"""

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional

# Anchor relative log paths to the project root (/home/bot-main) so the log
# file always lands in the right place regardless of cwd at startup.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def setup_logger(
    name: str = "Bot",
    level: str = "INFO",
    log_file: Optional[str] = "logs/bot.log",
    log_format: str = "[%(asctime)s] [%(levelname)s] %(message)s",
    date_format: str = "%Y-%m-%d %H:%M:%S"
) -> logging.Logger:
    """
    Setup and configure logger

    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file (None for console only)
        log_format: Log message format
        date_format: Date format for timestamps

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicate entries on reload
    logger.handlers.clear()

    # Prevent log records bubbling to root logger (avoids double console output)
    logger.propagate = False

    # Create formatter
    formatter = logging.Formatter(log_format, datefmt=date_format)

    # File handler — write everything DEBUG+ to disk
    if log_file:
        log_path = Path(log_file)

        # Resolve relative paths against the project root
        if not log_path.is_absolute():
            log_path = _PROJECT_ROOT / log_path

        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


class BotLogger:
    """Centralized logger for bot operations"""

    def __init__(self, config: dict):
        """Initialize bot logger with configuration"""
        self.logger = setup_logger(
            level=config.get("level", "INFO"),
            log_file=config.get("file", "logs/bot.log"),
            log_format=config.get("format", "[%(asctime)s] [%(levelname)s] %(message)s"),
            date_format=config.get("date_format", "%Y-%m-%d %H:%M:%S")
        )

    def debug(self, message: str) -> None:
        self.logger.debug(message)

    def info(self, message: str) -> None:
        self.logger.info(message)

    def warning(self, message: str) -> None:
        self.logger.warning(message)

    def error(self, message: str, exc_info: bool = False) -> None:
        self.logger.error(message, exc_info=exc_info)

    def critical(self, message: str, exc_info: bool = False) -> None:
        self.logger.critical(message, exc_info=exc_info)

    def command(self, user: str, command: str, guild: str) -> None:
        self.info(f"Command '{command}' executed by {user} in {guild}")

    def event(self, event_name: str, details: str = "") -> None:
        self.info(f"Event '{event_name}': {details}")

    def cog_load(self, cog_name: str) -> None:
        self.info(f"Loaded cog: {cog_name}")

    def cog_unload(self, cog_name: str) -> None:
        self.info(f"Unloaded cog: {cog_name}")