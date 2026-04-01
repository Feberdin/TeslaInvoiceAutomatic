"""
Purpose: Deliver invoice e-mails either via SMTP or at least via a local outbox log for debugging.
Input/Output: Records every outgoing message and optionally sends it through a configured SMTP server.
Invariants: Every recorded message contains recipients, subject and referenced attachment paths.
Debug: If sync says an e-mail was sent, check the outbox log first and then the SMTP settings and server logs.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from app.config import Settings


logger = logging.getLogger(__name__)


class DeliveryEmailService:
    def __init__(self, data_dir: Path, settings: Settings) -> None:
        self.outbox_path = data_dir / "email-outbox.log"
        self.default_from_email = settings.default_from_email
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_username = settings.smtp_username
        self.smtp_password = settings.smtp_password
        self.smtp_use_tls = settings.smtp_use_tls
        self.smtp_use_ssl = settings.smtp_use_ssl
        self.outbox_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host)

    def send_summary(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        attachment_paths: list[str],
        *,
        from_email: str | None = None,
    ) -> str:
        return self.send_message(recipients, subject, body, attachment_paths, from_email=from_email)

    def send_message(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        attachment_paths: list[str],
        *,
        from_email: str | None = None,
    ) -> str:
        effective_from_email = from_email or self.default_from_email
        timestamp = datetime.now(timezone.utc).isoformat()
        record = (
            f"[{timestamp}] from={effective_from_email} "
            f"to={','.join(recipients)} subject={subject!r} "
            f"attachments={attachment_paths!r} body={body!r}\n"
        )
        with self.outbox_path.open("a", encoding="utf-8") as handle:
            handle.write(record)

        logger.debug(
            "Recorded outgoing e-mail in outbox. recipients=%s attachments=%s smtp_configured=%s",
            recipients,
            len(attachment_paths),
            self.smtp_configured,
        )

        if not self.smtp_configured:
            logger.info("SMTP is not configured. Message stayed in outbox only. recipients=%s", recipients)
            return "outbox"

        message = EmailMessage()
        message["From"] = effective_from_email
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message.set_content(body)

        # Attachments are embedded so the invoice test matches the later real accounting flow.
        for attachment_path in attachment_paths:
            file_path = Path(attachment_path)
            if not file_path.exists():
                raise RuntimeError(
                    f"Der Anhang {attachment_path} wurde fuer den E-Mail-Versand erwartet, ist aber nicht vorhanden."
                )
            message.add_attachment(
                file_path.read_bytes(),
                maintype="application",
                subtype="pdf",
                filename=file_path.name,
            )

        try:
            logger.debug(
                "Attempting SMTP delivery. host=%s port=%s tls=%s ssl=%s username_set=%s recipients=%s",
                self.smtp_host,
                self.smtp_port,
                self.smtp_use_tls,
                self.smtp_use_ssl,
                bool(self.smtp_username),
                recipients,
            )
            if self.smtp_use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=20)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20)

            with server:
                if not self.smtp_use_ssl and self.smtp_use_tls:
                    server.starttls()
                if self.smtp_username:
                    server.login(self.smtp_username, self.smtp_password)
                server.send_message(message)
        except Exception as exc:
            logger.exception(
                "SMTP delivery failed. host=%s port=%s tls=%s ssl=%s recipients=%s",
                self.smtp_host,
                self.smtp_port,
                self.smtp_use_tls,
                self.smtp_use_ssl,
                recipients,
            )
            raise RuntimeError(
                "SMTP-Versand fehlgeschlagen. Bitte Host, Port, TLS/SSL, Benutzername und Passwort in Unraid pruefen."
            ) from exc

        logger.info("SMTP delivery succeeded. recipients=%s attachments=%s", recipients, len(attachment_paths))
        return "smtp"
