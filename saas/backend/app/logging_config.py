"""
Purpose: Configure consistent console logging for API and worker containers.
Input/Output: Receives the target log level and applies a single root logging setup.
Invariants: Logs include timestamp, level, logger name and message; sensitive tokens are never added here.
Debug: If logs look incomplete, verify the selected `LOG_LEVEL` and whether another config overwrote the root logger.
"""

from __future__ import annotations

import logging


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

