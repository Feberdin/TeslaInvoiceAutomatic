"""
Purpose: Verify Tesla token import, token encryption and charging-history parsing for the live Tesla sync path.
Input/Output: Uses pure helpers and does not call Tesla over the network.
Invariants: Cache JSON import keeps account metadata intact, encrypted tokens can be read back and Tesla charging history becomes stable internal session objects.
Debug: If real Tesla connection fails after a refactor, reproduce the token import or payload parsing here before changing worker logic.
"""

from __future__ import annotations

import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.errors import TeslaTokenImportError
from app.services.tesla_owner import build_imported_tokens, parse_owner_charging_sessions
from app.token_store import decrypt_secret, encrypt_secret


class TeslaOwnerTests(unittest.TestCase):
    def test_build_imported_tokens_from_cache_json(self) -> None:
        cache_payload = {
            "driver@example.com": {
                "url": "https://auth.tesla.com/",
                "sso": {
                    "access_token": "header.payload.signature",
                    "refresh_token": "refresh-token-123",
                    "expires_at": 1_800_000_000,
                },
            }
        }

        imported = build_imported_tokens(
            tesla_account_email="driver@example.com",
            cache_json=json.dumps(cache_payload),
            access_token=None,
            refresh_token=None,
            auth_base_url="https://auth.tesla.com",
        )

        self.assertEqual("driver@example.com", imported.tesla_account_email)
        self.assertEqual("refresh-token-123", imported.refresh_token)
        self.assertEqual("https://auth.tesla.com", imported.auth_base_url)
        self.assertIsNotNone(imported.expires_at)

    def test_encrypt_and_decrypt_secret(self) -> None:
        encrypted = encrypt_secret("super-secret-token")
        self.assertTrue(encrypted.startswith("enc::"))
        self.assertEqual("super-secret-token", decrypt_secret(encrypted))

    def test_parse_owner_charging_sessions(self) -> None:
        payload = {
            "data": [
                {
                    "vin": "5YJ3E1EA7JF000001",
                    "chargeStopDateTime": "2026-03-31T12:15:00Z",
                    "siteLocationName": "Berlin Sued",
                    "totalAmount": {"amount": "21,50", "currency": "EUR"},
                    "invoices": [
                        {
                            "contentId": "invoice-123",
                            "fileName": "invoice-123.pdf",
                        }
                    ],
                }
            ]
        }

        sessions = parse_owner_charging_sessions(payload, requested_vin="5YJ3E1EA7JF000001")

        self.assertEqual(1, len(sessions))
        self.assertEqual("invoice-123", sessions[0].invoice_id)
        self.assertEqual(Decimal("21.50"), sessions[0].amount)
        self.assertEqual("EUR", sessions[0].currency)
        self.assertEqual("Berlin Sued", sessions[0].location)

    def test_manual_token_import_requires_secret(self) -> None:
        imported = build_imported_tokens(
            tesla_account_email="driver@example.com",
            cache_json=None,
            access_token=None,
            refresh_token="refresh-token-123",
            auth_base_url="https://auth.tesla.com",
        )
        self.assertEqual("driver@example.com", imported.tesla_account_email)
        self.assertEqual("refresh-token-123", imported.refresh_token)

    def test_token_import_rejects_empty_payload(self) -> None:
        with self.assertRaises(TeslaTokenImportError):
            build_imported_tokens(
                tesla_account_email="driver@example.com",
                cache_json=None,
                access_token=None,
                refresh_token=None,
                auth_base_url="https://auth.tesla.com",
            )


if __name__ == "__main__":
    unittest.main()
