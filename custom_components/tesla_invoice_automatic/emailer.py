"""SMTP helper for sending Tesla invoice PDFs.

Purpose:
    Build and send one email with PDF attachment using explicit, debuggable SMTP
    settings instead of relying on hidden platform behavior.
Input/Output:
    Accepts integration config, a PDF byte payload, and invoice metadata; sends
    one email or raises a descriptive delivery error.
Important invariants:
    Required SMTP fields are validated before opening the network connection.
    Secrets are never written to logs.
How to debug:
    Verify SMTP host, port, security mode, sender, and recipient first. Then
    test with `LOG_LEVEL=debug` and check the exact failure class in the log.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .const import (
    CONF_RECIPIENT_EMAIL,
    CONF_SENDER_EMAIL,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSWORD,
    CONF_SMTP_PORT,
    CONF_SMTP_SECURITY,
    CONF_SMTP_USERNAME,
    SMTP_SECURITY_NONE,
    SMTP_SECURITY_SSL,
    SMTP_SECURITY_STARTTLS,
)
from .errors import EmailDeliveryError
from .models import InvoicePdfFile

_LOGGER = logging.getLogger(__name__)


def validate_email_config(config: dict[str, Any]) -> None:
    """Validate SMTP configuration before any connection attempt.

    Example:
        validate_email_config({"smtp_host": "smtp.example.org", ...})
    """

    missing = [
        key
        for key in (
            CONF_SMTP_HOST,
            CONF_SMTP_PORT,
            CONF_SENDER_EMAIL,
            CONF_RECIPIENT_EMAIL,
        )
        if not str(config.get(key) or "").strip()
    ]
    if missing:
        raise EmailDeliveryError(
            "SMTP-Konfiguration unvollstaendig. Bitte diese Felder pruefen: "
            + ", ".join(missing)
        )


def send_invoice_email(
    config: dict[str, Any],
    invoice_file: InvoicePdfFile,
    pdf_content: bytes,
    pdf_path: Path,
) -> None:
    """Send one PDF invoice mail through SMTP."""

    validate_email_config(config)
    if not pdf_content:
        raise EmailDeliveryError(
            f"Rechnung {invoice_file.file_name} enthaelt keine PDF-Daten und kann nicht versendet werden."
        )

    host = str(config[CONF_SMTP_HOST]).strip()
    port = int(config[CONF_SMTP_PORT])
    sender = str(config[CONF_SENDER_EMAIL]).strip()
    recipient = str(config[CONF_RECIPIENT_EMAIL]).strip()
    username = str(config.get(CONF_SMTP_USERNAME) or "").strip()
    password = str(config.get(CONF_SMTP_PASSWORD) or "").strip()
    security = str(config.get(CONF_SMTP_SECURITY) or SMTP_SECURITY_STARTTLS).strip()

    message = EmailMessage()
    message["Subject"] = f"Tesla Lade-Rechnung {invoice_file.file_name}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(_build_message_body(invoice_file, pdf_path))
    message.add_attachment(
        pdf_content,
        maintype="application",
        subtype="pdf",
        filename=pdf_path.name,
    )

    context = ssl.create_default_context()

    try:
        if security == SMTP_SECURITY_SSL:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
                _login_if_needed(smtp, username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                if security == SMTP_SECURITY_STARTTLS:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                elif security != SMTP_SECURITY_NONE:
                    raise EmailDeliveryError(
                        f"Unbekannter SMTP-Sicherheitsmodus '{security}'. "
                        "Erlaubt sind: starttls, ssl, none."
                    )
                _login_if_needed(smtp, username, password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as err:
        raise EmailDeliveryError(
            "E-Mail mit Tesla-Rechnung konnte nicht gesendet werden. "
            f"SMTP-Server: {host}:{port}, Empfaenger: {recipient}. Fehler: {err}"
        ) from err

    _LOGGER.info(
        "Tesla-Rechnung %s erfolgreich per E-Mail an %s versendet.",
        invoice_file.file_name,
        recipient,
    )


def _login_if_needed(smtp: smtplib.SMTP, username: str, password: str) -> None:
    """Authenticate only when the operator provided SMTP credentials."""

    if username:
        smtp.login(username, password)


def _build_message_body(invoice_file: InvoicePdfFile, pdf_path: Path) -> str:
    """Create a friendly, support-oriented email body."""

    return (
        "Automatisch versendete Tesla Lade-Rechnung.\n\n"
        f"Datei: {invoice_file.file_name}\n"
        f"Datei-ID: {invoice_file.file_id}\n"
        f"Letzte Aenderung: {invoice_file.modified_at.isoformat()}\n"
        f"Dateigroesse: {invoice_file.size_bytes} Bytes\n"
        f"Quelle: {pdf_path}\n"
    )
