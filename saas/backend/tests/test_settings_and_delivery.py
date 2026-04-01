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
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.errors import EmailDeliveryError, GoogleApiError
from app.services.emailer import DeliveryEmailService
from app.services.google_oauth import GOOGLE_GMAIL_SEND_SCOPE

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
            self.assertIn("to=receipts@in.circula.com", outbox_content)
            self.assertIn("cc=user@example.com", outbox_content)

    def test_google_delivery_is_preferred_over_smtp_when_connected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "DATA_DIR": temp_dir,
                    "DEFAULT_FROM_EMAIL": "no-reply@example.com",
                    "SMTP_HOST": "smtp.example.com",
                },
                clear=False,
            ):
                settings = get_settings()

            service = DeliveryEmailService(Path(temp_dir), settings)
            google_account = SimpleNamespace(
                google_email="fahrer@example.com",
                access_token="enc::token",
                refresh_token=None,
                oauth_scope=f"openid email profile {GOOGLE_GMAIL_SEND_SCOPE}",
            )

            with patch.object(service.google_client, "send_message") as mocked_send:
                delivery_mode = service.send_message(
                    recipients=["receipts@in.circula.com"],
                    subject="Circula via Google",
                    body="Test body",
                    attachment_paths=[],
                    from_email="fahrer@example.com",
                    cc_recipients=["user@example.com"],
                    google_account=google_account,
                )

            self.assertEqual("gmail", delivery_mode)
            mocked_send.assert_called_once()
            sent_message = mocked_send.call_args.args[1]
            self.assertEqual("fahrer@example.com", sent_message["From"])
            outbox_content = (Path(temp_dir) / "email-outbox.log").read_text(encoding="utf-8")
            self.assertIn("transport=gmail", outbox_content)

    def test_google_delivery_defaults_from_to_connected_google_mailbox(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "DATA_DIR": temp_dir,
                    "DEFAULT_FROM_EMAIL": "no-reply@example.com",
                },
                clear=False,
            ):
                settings = get_settings()

            service = DeliveryEmailService(Path(temp_dir), settings)
            google_account = SimpleNamespace(
                google_email="fahrer@example.com",
                access_token="enc::token",
                refresh_token=None,
                oauth_scope=f"openid email profile {GOOGLE_GMAIL_SEND_SCOPE}",
            )

            with patch.object(service.google_client, "send_message") as mocked_send:
                delivery_mode = service.send_message(
                    recipients=["buchhaltung@example.com"],
                    subject="Google Default Sender",
                    body="Test body",
                    attachment_paths=[],
                    google_account=google_account,
                )

            self.assertEqual("gmail", delivery_mode)
            sent_message = mocked_send.call_args.args[1]
            self.assertEqual("fahrer@example.com", sent_message["From"])

    def test_google_delivery_reports_alias_mismatch_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "DATA_DIR": temp_dir,
                    "DEFAULT_FROM_EMAIL": "no-reply@example.com",
                },
                clear=False,
            ):
                settings = get_settings()

            service = DeliveryEmailService(Path(temp_dir), settings)
            google_account = SimpleNamespace(
                google_email="fahrer@example.com",
                access_token="enc::token",
                refresh_token=None,
                oauth_scope=f"openid email profile {GOOGLE_GMAIL_SEND_SCOPE}",
            )

            with patch.object(
                service.google_client,
                "send_message",
                side_effect=GoogleApiError("Google Gmail API konnte die Nachricht nicht senden. HTTP-Status: 400."),
            ):
                with self.assertRaisesRegex(EmailDeliveryError, "passt nicht zum verbundenen Google-Konto"):
                    service.send_message(
                        recipients=["receipts@in.circula.com"],
                        subject="Circula via Google",
                        body="Test body",
                        attachment_paths=[],
                        from_email="anderer.absender@example.net",
                        google_account=google_account,
                    )


if __name__ == "__main__":
    unittest.main()
