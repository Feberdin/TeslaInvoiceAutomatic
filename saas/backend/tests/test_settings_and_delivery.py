"""
Purpose: Cover beta-specific configuration and delivery behavior without touching external systems.
Input/Output: Uses patched environment variables and a temporary outbox file to verify validation and sender overrides.
Invariants: `SYNC_INTERVAL_MINUTES` must win over seconds and Circula requires a dedicated employee sender address.
Debug: If the worker cadence or Circula sender logic breaks, reproduce the smallest case here before changing runtime code.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.emailer import DeliveryEmailService

try:
    from app.schemas import EmailSettingsRequest
except ModuleNotFoundError:  # pragma: no cover - local fallback when optional runtime deps are absent
    EmailSettingsRequest = None


class SettingsAndDeliveryTests(unittest.TestCase):
    def test_sync_interval_minutes_override_seconds(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SYNC_INTERVAL_MINUTES": "45",
                "SYNC_INTERVAL_SECONDS": "120",
            },
            clear=False,
        ):
            settings = get_settings()

        self.assertEqual(2700, settings.sync_interval_seconds)

    def test_circula_requires_employee_sender_email(self) -> None:
        if EmailSettingsRequest is None:
            self.skipTest("Pydantic ist lokal nicht installiert. Die Circula-Validierung wird im Container geprueft.")

        with self.assertRaisesRegex(ValueError, "Mitarbeiter-Absenderadresse"):
            EmailSettingsRequest(
                recipients=["user@example.com"],
                subject_template="Neue Tesla-Rechnungen fuer {email}",
                attach_pdf=True,
                accounting_targets=["Circula"],
                employee_sender_email=None,
            )

    def test_circula_accepts_employee_sender_email(self) -> None:
        if EmailSettingsRequest is None:
            self.skipTest("Pydantic ist lokal nicht installiert. Die Circula-Validierung wird im Container geprueft.")

        payload = EmailSettingsRequest(
            recipients=["user@example.com"],
            subject_template="Neue Tesla-Rechnungen fuer {email}",
            attach_pdf=True,
            accounting_targets=["Circula"],
            employee_sender_email="fahrer@example.com",
        )

        self.assertEqual("fahrer@example.com", payload.employee_sender_email)

    def test_outbox_records_effective_sender_override_and_cc(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "DATA_DIR": temp_dir,
                    "DEFAULT_FROM_EMAIL": "no-reply@example.com",
                    "SMTP_HOST": "",
                },
                clear=False,
            ):
                settings = get_settings()

            service = DeliveryEmailService(Path(temp_dir), settings)
            delivery_mode = service.send_message(
                recipients=["receipts@in.circula.com"],
                subject="Circula Test",
                body="Test body",
                attachment_paths=[],
                from_email="fahrer@example.com",
                cc_recipients=["user@example.com"],
            )

            self.assertEqual("outbox", delivery_mode)
            outbox_content = (Path(temp_dir) / "email-outbox.log").read_text(encoding="utf-8")
            self.assertIn("from=fahrer@example.com", outbox_content)
            self.assertIn("reply_to=fahrer@example.com", outbox_content)
            self.assertIn("to=receipts@in.circula.com", outbox_content)
            self.assertIn("cc=user@example.com", outbox_content)


if __name__ == "__main__":
    unittest.main()
