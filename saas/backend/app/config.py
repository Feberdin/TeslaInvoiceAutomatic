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

from app.utils import validate_email_address


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    app_base_url: str
    log_level: str
    secret_key: str
    demo_mode: bool
    database_url: str
    data_dir: Path
    sync_interval_seconds: int
    default_from_email: str
    demo_user_email: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool
    smtp_use_ssl: bool
    enable_tesla_fleet_oauth: bool
    enable_tesla_owner_import: bool
    tesla_client_id: str
    tesla_client_secret: str
    tesla_fleet_api_base_url: str
    tesla_oauth_scope: str
    tesla_oauth_redirect_path: str
    admin_emails: tuple[str, ...] = ()
    tesla_partner_token_scope: str = "openid user_data vehicle_device_data vehicle_cmds vehicle_charging_cmds"


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name, str(default)).strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _read_email_list(name: str) -> tuple[str, ...]:
    raw_value = os.getenv(name, "")
    emails: list[str] = []
    for candidate in raw_value.split(","):
        normalized_candidate = candidate.strip()
        if not normalized_candidate:
            continue
        emails.append(validate_email_address(normalized_candidate))
    return tuple(dict.fromkeys(emails))


def get_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "./data")).expanduser()
    redirect_path = os.getenv("TESLA_OAUTH_REDIRECT_PATH", "/api/v1/tesla/oauth/callback").strip() or "/api/v1/tesla/oauth/callback"
    if not redirect_path.startswith("/"):
        redirect_path = f"/{redirect_path}"

    return Settings(
        app_name=os.getenv("APP_NAME", "Tesla Invoice Automatic SaaS"),
        app_env=os.getenv("APP_ENV", "development"),
        app_base_url=os.getenv("APP_BASE_URL", "http://localhost:8000"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        secret_key=os.getenv("SECRET_KEY", "tesla-invoice-demo-secret-change-me"),
        demo_mode=_read_bool("DEMO_MODE", True),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/local_demo.db"),
        data_dir=data_dir,
        sync_interval_seconds=max(int(os.getenv("SYNC_INTERVAL_SECONDS", "1800")), 60),
        default_from_email=os.getenv("DEFAULT_FROM_EMAIL", "no-reply@tesla-invoice-demo.local"),
        demo_user_email=os.getenv("DEMO_USER_EMAIL", "demo@feberdin.local").strip().lower(),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=max(int(os.getenv("SMTP_PORT", "587")), 1),
        smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_use_tls=_read_bool("SMTP_USE_TLS", True),
        smtp_use_ssl=_read_bool("SMTP_USE_SSL", False),
        enable_tesla_fleet_oauth=_read_bool("ENABLE_TESLA_FLEET_OAUTH", True),
        enable_tesla_owner_import=_read_bool("ENABLE_TESLA_OWNER_IMPORT", True),
        tesla_client_id=os.getenv("TESLA_CLIENT_ID", "").strip(),
        tesla_client_secret=os.getenv("TESLA_CLIENT_SECRET", "").strip(),
        tesla_fleet_api_base_url=os.getenv(
            "TESLA_FLEET_API_BASE_URL",
            "https://fleet-api.prd.eu.vn.cloud.tesla.com",
        ).strip().rstrip("/"),
        tesla_oauth_scope=os.getenv(
            "TESLA_OAUTH_SCOPE",
            "openid offline_access user_data vehicle_device_data vehicle_charging_cmds",
        ).strip(),
        tesla_oauth_redirect_path=redirect_path,
        admin_emails=_read_email_list("ADMIN_EMAILS"),
        tesla_partner_token_scope=os.getenv(
            "TESLA_PARTNER_TOKEN_SCOPE",
            "openid user_data vehicle_device_data vehicle_cmds vehicle_charging_cmds",
        ).strip(),
    )
