import logging
import sys
from typing import Any

import structlog


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structured logging with structlog."""

    # Configure structlog
    structlog.configure(
        processors=[
            # Add log level to event dict
            structlog.stdlib.add_log_level,
            # Add timestamp
            structlog.processors.TimeStamper(fmt="iso"),
            # If the log entry has a "stack_trace" key, format it
            structlog.processors.StackInfoRenderer(),
            # Format exception info
            structlog.processors.format_exc_info,
            # Decode unicode
            structlog.processors.UnicodeDecoder(),
            # Final renderer - JSON for production, console for development
            structlog.dev.ConsoleRenderer() if sys.stderr.isatty() else structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard logging（防止重复添加 handler）
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Suppress noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str, **initial_context: Any) -> structlog.stdlib.BoundLogger:
    """Get a bound logger with initial context."""
    return structlog.get_logger(name, **initial_context)


def print_status(message: str, level: str = "info") -> None:
    """Print a formatted status message to console."""
    colors = {
        "info": "\033[94m",     # Blue
        "success": "\033[92m",  # Green
        "warning": "\033[93m",  # Yellow
        "error": "\033[91m",    # Red
    }
    reset = "\033[0m"
    color = colors.get(level, colors["info"])
    try:
        print(f"{color}[{level.upper()}]{reset} {message}")
    except UnicodeEncodeError:
        # Fallback for Windows console encoding issues
        print(f"[{level.upper()}] {message}")
