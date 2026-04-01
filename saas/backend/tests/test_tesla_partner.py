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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.admin import user_is_admin
from app.config import Settings
from app.services.tesla_partner import PUBLIC_KEY_WELL_KNOWN_PATH, TeslaPartnerAdminService


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


if __name__ == "__main__":
    unittest.main()
