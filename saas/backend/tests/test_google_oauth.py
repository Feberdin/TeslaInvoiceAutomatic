"""
Purpose: Verify Google OAuth helpers for combined login and Gmail sending without contacting Google.
Input/Output: Uses pure helper calls and lightweight model instances to validate scopes, redirects and transport readiness.
Invariants: Google login must only be advertised with full client credentials, and Gmail sending requires both a token and the `gmail.send` scope.
Debug: If Google buttons show up unexpectedly or Gmail is not selected as delivery channel, reproduce the effective settings and scopes here first.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.services.google_oauth import (
    GOOGLE_GMAIL_SEND_SCOPE,
    build_google_authorization_request,
    google_gmail_send_available,
    google_oauth_available,
)


def _settings(*, client_id: str = "google-client-id", client_secret: str = "google-client-secret") -> Settings:
    return Settings(
        app_name="Test",
        app_env="test",
        app_base_url="https://tesla-invoice.example.test",
        log_level="INFO",
        secret_key="secret",
        demo_mode=True,
        database_url="sqlite:///./data/test.db",
        data_dir=Path("/tmp"),
        sync_interval_seconds=1800,
        default_from_email="no-reply@example.com",
        demo_user_email="demo@example.com",
        smtp_host="",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        smtp_use_tls=True,
        smtp_use_ssl=False,
        enable_google_oauth=True,
        google_client_id=client_id,
        google_client_secret=client_secret,
        google_oauth_scope=f"openid email profile {GOOGLE_GMAIL_SEND_SCOPE}",
        google_oauth_redirect_path="/oauth/callback",
        google_oauth_prompt="consent select_account",
        enable_tesla_fleet_oauth=True,
        enable_tesla_owner_import=True,
        tesla_client_id="tesla-client-id",
        tesla_client_secret="tesla-client-secret",
        tesla_fleet_api_base_url="https://fleet-api.prd.eu.vn.cloud.tesla.com",
        tesla_oauth_scope="openid offline_access user_data vehicle_device_data vehicle_charging_cmds",
        tesla_oauth_redirect_path="/api/v1/tesla/oauth/callback",
    )


class GoogleOAuthTests(unittest.TestCase):
    def test_google_oauth_available_requires_client_credentials(self) -> None:
        self.assertTrue(google_oauth_available(_settings()))
        self.assertFalse(google_oauth_available(_settings(client_id="", client_secret="secret")))
        self.assertFalse(google_oauth_available(_settings(client_id="client", client_secret="")))

    def test_google_authorization_request_contains_redirect_and_gmail_scope(self) -> None:
        authorization_request = build_google_authorization_request(_settings())

        self.assertIn("client_id=google-client-id", authorization_request.url)
        self.assertIn(
            "redirect_uri=https%3A%2F%2Ftesla-invoice.example.test%2Foauth%2Fcallback",
            authorization_request.url,
        )
        self.assertIn(parse_quote(GOOGLE_GMAIL_SEND_SCOPE), authorization_request.url)
        self.assertIn("access_type=offline", authorization_request.url)
        self.assertTrue(authorization_request.state)
        self.assertTrue(authorization_request.nonce)

    def test_google_gmail_send_requires_scope_and_token(self) -> None:
        account = SimpleNamespace(
            google_email="fahrer@example.com",
            access_token="enc::token",
            refresh_token=None,
            oauth_scope=f"openid email profile {GOOGLE_GMAIL_SEND_SCOPE}",
        )
        self.assertTrue(google_gmail_send_available(account))

        account.oauth_scope = "openid email profile"
        self.assertFalse(google_gmail_send_available(account))

        account.oauth_scope = f"openid email profile {GOOGLE_GMAIL_SEND_SCOPE}"
        account.access_token = None
        self.assertFalse(google_gmail_send_available(account))


def parse_quote(value: str) -> str:
    return value.replace(":", "%3A").replace("/", "%2F")


if __name__ == "__main__":
    unittest.main()
