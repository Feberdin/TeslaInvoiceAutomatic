"""Constants for the Tesla Invoice Automatic integration.

Purpose:
    Keep all shared identifiers, defaults, and config keys in one place so the
    rest of the integration stays readable.
Input/Output:
    Imported by Home Assistant platform modules; no runtime side effects.
Important invariants:
    Keys defined here must stay stable because they are used in config entries
    and in the integration's persisted storage.
How to debug:
    If setup or options handling breaks, first confirm that the keys used in
    logs and config entries still match the constants in this file.
"""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "tesla_invoice_automatic"
PLATFORMS = ["sensor"]

MANUFACTURER = "Feberdin"

DEFAULT_NAME = "Tesla Invoice Automatic"
DEFAULT_POLL_INTERVAL_MINUTES = 15
DEFAULT_SMTP_PORT = 587
DEFAULT_HISTORY_DAYS = 365
DEFAULT_HISTORY_MAX_INVOICES = 50
DEFAULT_DEVICE_LANGUAGE = "de"
DEFAULT_DEVICE_COUNTRY = "DE"
DEFAULT_HTTP_LOCALE = "de_DE"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_OWNERSHIP_BASE_URL = "https://ownership.tesla.com/mobile-app/charging"
FALLBACK_OWNERSHIP_BASE_URLS = (
    DEFAULT_OWNERSHIP_BASE_URL,
    "https://owner-api.teslamotors.com/bff/v2/mobile-app/charging",
)

COORDINATOR_NAME = "tesla_invoice_automatic_coordinator"
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_state"
INVOICE_DIRECTORY_NAME = "invoices"

CONF_TESLA_HA_ENTRY_ID = "tesla_ha_entry_id"
CONF_VIN = "vin"
CONF_RECIPIENT_EMAIL = "recipient_email"
CONF_SENDER_EMAIL = "sender_email"
CONF_SMTP_HOST = "smtp_host"
CONF_SMTP_PORT = "smtp_port"
CONF_SMTP_USERNAME = "smtp_username"
CONF_SMTP_PASSWORD = "smtp_password"
CONF_SMTP_SECURITY = "smtp_security"
CONF_POLL_INTERVAL_MINUTES = "poll_interval_minutes"
CONF_DEVICE_LANGUAGE = "device_language"
CONF_DEVICE_COUNTRY = "device_country"
CONF_HTTP_LOCALE = "http_locale"
CONF_OWNERSHIP_BASE_URL = "ownership_base_url"

SMTP_SECURITY_STARTTLS = "starttls"
SMTP_SECURITY_SSL = "ssl"
SMTP_SECURITY_NONE = "none"
SMTP_SECURITY_OPTIONS = [
    SMTP_SECURITY_STARTTLS,
    SMTP_SECURITY_SSL,
    SMTP_SECURITY_NONE,
]

SERVICE_SEND_LATEST = "send_latest_invoice"
SERVICE_SEND_HISTORY = "send_historical_invoices"

ATTR_LAST_INVOICE_ID = "last_invoice_id"
ATTR_LAST_EMAIL_AT = "last_email_at"
ATTR_LAST_ERROR = "last_error"
ATTR_LAST_DOWNLOADED_FILE = "last_downloaded_file"
ATTR_LAST_SESSION_ID = "last_session_id"
ATTR_PENDING_INVOICE_COUNT = "pending_invoice_count"
ATTR_LAST_HISTORY_IMPORT_AT = "last_history_import_at"
ATTR_LAST_HISTORY_DAYS = "last_history_days"
ATTR_LINKED_TESLA_HA = "linked_tesla_ha"

SCAN_INTERVAL = timedelta(minutes=DEFAULT_POLL_INTERVAL_MINUTES)
