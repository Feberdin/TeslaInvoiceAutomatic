"""
Purpose: Verify the operator-only Tesla Fleet partner helpers without contacting Tesla over the network.
Input/Output: Uses temporary directories to create local key files and validates the derived admin status.
Invariants: Generated Fleet keys use PEM format, the public-key URL follows Tesla's well-known path and key rotation is explicit.
Debug: If the admin menu shows missing key state unexpectedly, reproduce the local status snapshot in these tests first.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.admin import user_is_admin
from app.config import Settings
from app.services.tesla_partner import PUBLIC_KEY_WELL_KNOWN_PATH, TeslaPartnerAdminService, _HttpResponse


class TeslaPartnerAdminTests(unittest.TestCase):
    def _settings(self, data_dir: Path) -> Settings:
        return Settings(
            app_name="Test",
            app_env="test",
            app_base_url="https://tesla-invoice.example.test",
            log_level="INFO",
            secret_key="secret",
            demo_mode=True,
            database_url="sqlite:///./data/test.db",
            data_dir=data_dir,
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
            google_client_id="google-client-id",
            google_client_secret="google-client-secret",
            google_oauth_scope="openid email profile https://www.googleapis.com/auth/gmail.send",
            google_oauth_redirect_path="/oauth/callback",
            google_oauth_prompt="consent select_account",
            enable_tesla_fleet_oauth=True,
            enable_tesla_owner_import=True,
            tesla_client_id="client-id",
            tesla_client_secret="client-secret",
            tesla_fleet_api_base_url="https://fleet-api.prd.eu.vn.cloud.tesla.com",
            tesla_oauth_scope="openid offline_access user_data vehicle_device_data vehicle_charging_cmds",
            tesla_oauth_redirect_path="/api/v1/tesla/oauth/callback",
            admin_emails=("admin@example.com",),
            tesla_partner_token_scope="openid user_data vehicle_device_data vehicle_cmds vehicle_charging_cmds",
        )

    def test_admin_email_check_uses_normalized_addresses(self) -> None:
        settings = self._settings(Path("/tmp"))
        self.assertTrue(user_is_admin(settings, "Admin@Example.com"))
        self.assertFalse(user_is_admin(settings, "user@example.com"))

    def test_generate_key_pair_creates_pem_files_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TeslaPartnerAdminService(self._settings(Path(temp_dir)))

            initial_status = service.current_status()
            self.assertFalse(initial_status.public_key_present)

            result = service.generate_key_pair()
            updated_status = service.current_status()

            self.assertEqual("generated", result.status)
            self.assertTrue(updated_status.public_key_present)
            self.assertTrue(updated_status.private_key_present)
            self.assertIn("BEGIN PUBLIC KEY", updated_status.public_key_pem or "")
            self.assertIn(PUBLIC_KEY_WELL_KNOWN_PATH, updated_status.public_key_url)
            self.assertTrue(updated_status.public_key_fingerprint)

    def test_generate_key_pair_requires_force_before_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TeslaPartnerAdminService(self._settings(Path(temp_dir)))
            service.generate_key_pair()

            with self.assertRaises(ValueError):
                service.generate_key_pair()

            result = service.generate_key_pair(force=True)
            self.assertEqual("generated", result.status)

    def test_register_partner_account_sends_domain_json_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TeslaPartnerAdminService(self._settings(Path(temp_dir)))
            service.generate_key_pair()

            captured: dict[str, object] = {}

            def fake_request(*, method, url, headers, request_label, body=None):
                captured["method"] = method
                captured["url"] = url
                captured["body"] = body
                return _HttpResponse(status=200, headers={}, body=b"{}")

            with (
                patch.object(service, "_request_partner_token", return_value="partner-token"),
                patch.object(service, "_request", side_effect=fake_request),
                patch.object(service, "verify_partner_registration", return_value=type("Result", (), {"message": "Verify ok"})()),
            ):
                result = service.register_partner_account()

            self.assertEqual("success", result.status)
            self.assertEqual("POST", captured["method"])
            self.assertIn("/api/1/partner_accounts", str(captured["url"]))
            self.assertEqual(b'{"domain": "tesla-invoice.example.test"}', captured["body"])

    def test_verify_partner_registration_maps_403_to_missing_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TeslaPartnerAdminService(self._settings(Path(temp_dir)))

            with (
                patch.object(service, "_request_partner_token", return_value="partner-token"),
                patch.object(
                    service,
                    "_request",
                    return_value=_HttpResponse(
                        status=403,
                        headers={},
                        body=b'{"error":"This account does not have access to tesla-invoice.example.test"}',
                    ),
                ),
            ):
                result = service.verify_partner_registration()

            self.assertEqual("missing", result.status)
            self.assertIn("noch keinen freigeschalteten Partner-Zugriff", result.message)


if __name__ == "__main__":
    unittest.main()
