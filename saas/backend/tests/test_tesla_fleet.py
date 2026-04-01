"""
Purpose: Verify official Tesla Fleet OAuth helpers and the defensive charging-history parser.
Input/Output: Uses pure helper calls without contacting Tesla over the network.
Invariants: The authorize URL must contain the configured callback and client id, and Fleet charging history must become stable internal session objects.
Debug: If Tesla OAuth starts redirecting incorrectly or live invoices stop parsing, reproduce the failing payloads here first.
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.services.tesla_fleet import build_tesla_authorization_request, parse_fleet_charging_history, tesla_oauth_available


class TeslaFleetTests(unittest.TestCase):
    def test_tesla_oauth_available_requires_client_id_and_secret(self) -> None:
        settings = Settings(
            app_name="Test",
            app_env="test",
            app_base_url="http://localhost:8000",
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
            enable_tesla_fleet_oauth=True,
            enable_tesla_owner_import=True,
            tesla_client_id="client-id",
            tesla_client_secret="client-secret",
            tesla_fleet_api_base_url="https://fleet-api.prd.eu.vn.cloud.tesla.com",
            tesla_oauth_scope="openid offline_access user_data vehicle_device_data vehicle_charging_cmds",
            tesla_oauth_redirect_path="/api/v1/tesla/oauth/callback",
        )

        self.assertTrue(tesla_oauth_available(settings))
        authorization_request = build_tesla_authorization_request(settings)
        self.assertIn("client_id=client-id", authorization_request.url)
        self.assertIn("redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fapi%2Fv1%2Ftesla%2Foauth%2Fcallback", authorization_request.url)
        self.assertTrue(authorization_request.state)

    def test_tesla_oauth_is_false_when_feature_toggle_is_disabled(self) -> None:
        settings = Settings(
            app_name="Test",
            app_env="test",
            app_base_url="http://localhost:8000",
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
            enable_tesla_fleet_oauth=False,
            enable_tesla_owner_import=True,
            tesla_client_id="client-id",
            tesla_client_secret="client-secret",
            tesla_fleet_api_base_url="https://fleet-api.prd.eu.vn.cloud.tesla.com",
            tesla_oauth_scope="openid offline_access user_data vehicle_device_data vehicle_charging_cmds",
            tesla_oauth_redirect_path="/api/v1/tesla/oauth/callback",
        )

        self.assertFalse(tesla_oauth_available(settings))

    def test_parse_fleet_charging_history_with_nested_invoices(self) -> None:
        payload = {
            "response": [
                {
                    "vin": "LRW3E7FS5RC049963",
                    "chargeStartDateTime": "2026-04-01T10:15:00Z",
                    "siteLocationName": "Supercharger Berlin Sued",
                    "totalAmount": {"amount": "18.75", "currency": "EUR"},
                    "invoices": [
                        {"id": "fleet-invoice-1"},
                    ],
                }
            ]
        }

        sessions = parse_fleet_charging_history(payload, requested_vin="LRW3E7FS5RC049963")

        self.assertEqual(1, len(sessions))
        self.assertEqual("fleet-invoice-1", sessions[0].invoice_id)
        self.assertEqual(Decimal("18.75"), sessions[0].amount)
        self.assertEqual("EUR", sessions[0].currency)
        self.assertEqual("Supercharger Berlin Sued", sessions[0].location)

    def test_parse_fleet_charging_history_with_string_amount_and_currency_symbol(self) -> None:
        payload = {
            "response": [
                {
                    "vin": "LRW3E7FS5RC049963",
                    "chargeStartDateTime": "2026-04-01T10:15:00Z",
                    "siteLocationName": "Rosengarten, Germany",
                    "invoiceAmount": "EUR 28,90",
                    "invoices": [
                        {"id": "fleet-invoice-2"},
                    ],
                }
            ]
        }

        sessions = parse_fleet_charging_history(payload, requested_vin="LRW3E7FS5RC049963")

        self.assertEqual(1, len(sessions))
        self.assertEqual(Decimal("28.90"), sessions[0].amount)
        self.assertEqual("EUR", sessions[0].currency)


if __name__ == "__main__":
    unittest.main()
