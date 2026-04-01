"""
Purpose: Deliver invoice e-mails via Google Mail, SMTP or at least a local outbox log for debugging.
Input/Output: Records every outgoing message and optionally sends it through a connected Google account or a configured SMTP server.
Invariants: Every recorded message contains recipients, subject and referenced attachment paths, and Google delivery always wins over SMTP when the user explicitly connected Gmail.
Debug: If sync says an e-mail was sent, check the outbox log first and then the Google/SMTP settings and provider logs.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import Settings
from app.errors import EmailDeliveryError, GoogleApiError, GoogleAuthenticationError
from app.services.google_oauth import GoogleOAuthClient, google_gmail_send_available

if TYPE_CHECKING:
    from app.models import GoogleAccount

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
        self.google_client = GoogleOAuthClient(settings)
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
        cc_recipients: list[str] | None = None,
        google_account: "GoogleAccount | None" = None,
    ) -> str:
        return self.send_message(
            recipients,
            subject,
            body,
            attachment_paths,
            from_email=from_email,
            cc_recipients=cc_recipients,
            google_account=google_account,
        )

    def send_message(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        attachment_paths: list[str],
        *,
        from_email: str | None = None,
        cc_recipients: list[str] | None = None,
        google_account: "GoogleAccount | None" = None,
    ) -> str:
        # Why this exists:
        # When the same Google account handles login and Gmail delivery, the most honest default sender is that
        # Google mailbox itself. Explicit product flows such as Circula can still override this with `from_email`.
        effective_from_email = from_email or (
            getattr(google_account, "google_email", None) if google_gmail_send_available(google_account) else None
        ) or self.default_from_email
        effective_cc = [recipient for recipient in (cc_recipients or []) if recipient]
        preferred_transport = "gmail" if google_gmail_send_available(google_account) else "smtp" if self.smtp_configured else "outbox"
        timestamp = datetime.now(timezone.utc).isoformat()
        record = (
            f"[{timestamp}] from={effective_from_email} "
            f"to={','.join(recipients)} subject={subject!r} "
            f"cc={','.join(effective_cc)} "
            f"transport={preferred_transport} "
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

        message = EmailMessage()
        message["From"] = effective_from_email
        message["To"] = ", ".join(recipients)
        if effective_cc:
            message["Cc"] = ", ".join(effective_cc)
        message["Subject"] = subject
        message.set_content(body)

        # Attachments are embedded so the invoice test matches the later real accounting flow.
        for attachment_path in attachment_paths:
            file_path = Path(attachment_path)
            if not file_path.exists():
                raise EmailDeliveryError(
                    f"Der Anhang {attachment_path} wurde fuer den E-Mail-Versand erwartet, ist aber nicht vorhanden."
                )
            message.add_attachment(
                file_path.read_bytes(),
                maintype="application",
                subtype="pdf",
                filename=file_path.name,
            )

        if google_gmail_send_available(google_account):
            try:
                logger.debug(
                    "Attempting Google Mail delivery. google_email=%s from=%s recipients=%s cc=%s",
                    getattr(google_account, "google_email", None),
                    effective_from_email,
                    recipients,
                    effective_cc,
                )
                self.google_client.send_message(google_account, message)
            except (GoogleAuthenticationError, GoogleApiError) as exc:
                logger.exception(
                    "Google Mail delivery failed. google_email=%s from=%s recipients=%s cc=%s",
                    getattr(google_account, "google_email", None),
                    effective_from_email,
                    recipients,
                    effective_cc,
                )
                google_email = str(getattr(google_account, "google_email", "") or "").strip().lower()
                effective_sender = (effective_from_email or "").strip().lower()
                if google_email and effective_sender and google_email != effective_sender:
                    raise EmailDeliveryError(
                        "Google Mailversand wurde von Gmail abgelehnt. Die sichtbare `Von`-Adresse "
                        f"`{effective_from_email}` passt nicht zum verbundenen Google-Konto `{google_email}`. "
                        "Gmail akzeptiert hier nur die Google-Adresse selbst oder einen dort bereits freigegebenen Alias. "
                        "Bitte entweder die Mitarbeiter-Adresse als Gmail-Alias einrichten oder fuer den Versand "
                        "eine passende Absenderadresse verwenden."
                    ) from exc

                raise EmailDeliveryError(
                    "Google Mailversand fehlgeschlagen. "
                    f"{exc}"
                ) from exc

            logger.info(
                "Google Mail delivery succeeded. google_email=%s from=%s recipients=%s cc=%s attachments=%s",
                getattr(google_account, "google_email", None),
                effective_from_email,
                recipients,
                effective_cc,
                len(attachment_paths),
            )
            return "gmail"

        if not self.smtp_configured:
            logger.info("No Google Mail or SMTP available. Message stayed in outbox only. recipients=%s", recipients)
            return "outbox"

        try:
            logger.debug(
                "Attempting SMTP delivery. host=%s port=%s tls=%s ssl=%s username_set=%s from=%s recipients=%s cc=%s",
                self.smtp_host,
                self.smtp_port,
                self.smtp_use_tls,
                self.smtp_use_ssl,
                bool(self.smtp_username),
                effective_from_email,
                recipients,
                effective_cc,
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
                # We deliberately only set the visible `From` header here. If a provider still rewrites the
                # sender, the remaining limitation is on the SMTP side and not caused by an extra Reply-To.
                server.send_message(message)
        except Exception as exc:
            logger.exception(
                "SMTP delivery failed. host=%s port=%s tls=%s ssl=%s from=%s recipients=%s cc=%s",
                self.smtp_host,
                self.smtp_port,
                self.smtp_use_tls,
                self.smtp_use_ssl,
                effective_from_email,
                recipients,
                effective_cc,
            )
            raise EmailDeliveryError(
                "SMTP-Versand fehlgeschlagen. Bitte Host, Port, TLS/SSL, Benutzername und Passwort in Unraid pruefen."
            ) from exc

        logger.info(
            "SMTP delivery succeeded. from=%s recipients=%s cc=%s attachments=%s",
            effective_from_email,
            recipients,
            effective_cc,
            len(attachment_paths),
        )
        return "smtp"
