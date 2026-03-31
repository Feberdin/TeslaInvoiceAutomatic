"""
Purpose: Centralize environment-based configuration for the MVP backend and worker.
Input/Output: Reads environment variables and exposes validated settings as a dataclass.
Invariants: Paths are normalized once, demo mode is explicit, defaults stay safe for local testing.
Debug: When behavior differs between environments, log or inspect the `Settings` values first.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    app_base_url: str
    log_level: str
    demo_mode: bool
    database_url: str
    data_dir: Path
    sync_interval_seconds: int
    default_from_email: str
    demo_user_email: str


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name, str(default)).strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def get_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "./data")).expanduser()

    return Settings(
        app_name=os.getenv("APP_NAME", "Tesla Invoice Automatic SaaS"),
        app_env=os.getenv("APP_ENV", "development"),
        app_base_url=os.getenv("APP_BASE_URL", "http://localhost:8000"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        demo_mode=_read_bool("DEMO_MODE", True),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/local_demo.db"),
        data_dir=data_dir,
        sync_interval_seconds=max(int(os.getenv("SYNC_INTERVAL_SECONDS", "1800")), 60),
        default_from_email=os.getenv("DEFAULT_FROM_EMAIL", "no-reply@tesla-invoice-demo.local"),
        demo_user_email=os.getenv("DEMO_USER_EMAIL", "demo@feberdin.local").strip().lower(),
    )

