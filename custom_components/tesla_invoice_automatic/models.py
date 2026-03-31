"""Domain models and pure helpers for Tesla charging invoice processing.

Purpose:
    Represent invoice PDFs discoverable through Tesla's ownership charging
    history and decide which ones still need to be emailed.
Input/Output:
    Receives decoded Tesla charging-history payloads and returns normalized
    Python objects.
Important invariants:
    An invoice is uniquely identified by Tesla's `contentId`, and sorting stays
    newest-first so user-visible status is deterministic.
How to debug:
    If invoices are skipped unexpectedly, compare `content_id`, `vin`,
    `charged_at`, and the stored processed IDs in Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ChargingInvoiceDocument:
    """Normalized representation of one downloadable Tesla invoice PDF."""

    content_id: str
    file_name: str
    invoice_type: str | None
    session_id: str | None
    vin: str
    location_name: str | None
    country_code: str | None
    charged_at: datetime | None
    raw_payload: dict[str, Any]


@dataclass(slots=True)
class ProcessingResult:
    """Summary exposed by the coordinator after one processing pass."""

    processed_invoice_ids: list[str]
    last_invoice_id: str | None
    last_session_id: str | None
    last_downloaded_file: str | None
    last_email_at: str | None
    last_error: str | None
    pending_invoice_count: int
    last_history_import_at: str | None = None
    last_history_days: int | None = None
    last_fetch_attempt_at: str | None = None
    last_successful_fetch_at: str | None = None
    last_fetch_duration_seconds: float | None = None
    last_run_status: str | None = None
    last_run_processed_count: int = 0
    invoices_sent_total: int = 0
    invoices_sent_this_month: int = 0
    consecutive_failures: int = 0


def parse_charging_history(payload: Any) -> list[ChargingInvoiceDocument]:
    """Convert Tesla charging history JSON into normalized invoice documents."""

    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []

    invoices: list[ChargingInvoiceDocument] = []
    for session in data:
        if not isinstance(session, dict):
            continue

        charged_at = _parse_datetime(
            session.get("unlatchDateTime")
            or session.get("chargeStopDateTime")
            or session.get("chargeStartDateTime")
        )
        session_id = _string_or_none(session.get("sessionId") or session.get("chargeSessionId"))
        vin = _string_or_none(session.get("vin")) or ""
        location_name = _string_or_none(
            session.get("siteLocationName") or session.get("siteName")
        )
        country_code = _string_or_none(session.get("countryCode"))

        for invoice in session.get("invoices") or []:
            if not isinstance(invoice, dict):
                continue
            content_id = _string_or_none(invoice.get("contentId"))
            file_name = _string_or_none(invoice.get("fileName"))
            if not content_id or not file_name or not vin:
                continue
            invoices.append(
                ChargingInvoiceDocument(
                    content_id=content_id,
                    file_name=file_name,
                    invoice_type=_string_or_none(invoice.get("invoiceType")),
                    session_id=session_id,
                    vin=vin,
                    location_name=location_name,
                    country_code=country_code,
                    charged_at=charged_at,
                    raw_payload=session,
                )
            )

    invoices.sort(
        key=lambda item: item.charged_at.timestamp() if item.charged_at else 0.0,
        reverse=True,
    )
    return invoices


def select_pending_invoices(
    invoices: list[ChargingInvoiceDocument],
    processed_invoice_ids: set[str],
) -> list[ChargingInvoiceDocument]:
    """Return only invoices that have not been emailed yet."""

    return [item for item in invoices if item.content_id not in processed_invoice_ids]


def filter_invoices_by_age(
    invoices: list[ChargingInvoiceDocument],
    *,
    days_back: int,
    now: datetime | None = None,
) -> list[ChargingInvoiceDocument]:
    """Return invoices inside the requested historical import window."""

    if days_back <= 0:
        return list(invoices)

    reference_now = now or datetime.now(timezone.utc)
    cutoff = reference_now - timedelta(days=days_back)
    return [
        item
        for item in invoices
        if item.charged_at is None or _ensure_aware(item.charged_at) >= cutoff
    ]


def build_invoice_file_path(base_dir: Path, invoice: ChargingInvoiceDocument) -> Path:
    """Create a readable and stable local target path for one invoice."""

    charged_date = (
        _ensure_aware(invoice.charged_at).strftime("%Y-%m-%d")
        if invoice.charged_at
        else "unknown-date"
    )
    location = _sanitize_filename(invoice.location_name or "unknown-location")
    original_name = _sanitize_filename(invoice.file_name)
    if not original_name.lower().endswith(".pdf"):
        original_name = f"{original_name}.pdf"
    return base_dir / f"{charged_date}--{location}--{invoice.content_id}--{original_name}"


def current_month_key(reference: datetime | None = None) -> str:
    """Return a stable `YYYY-MM` key for monthly statistics."""

    effective_reference = _ensure_aware(reference or datetime.now(timezone.utc))
    return effective_reference.strftime("%Y-%m")


def normalize_monthly_invoice_count(
    stored_month_key: str | None,
    count: int,
    *,
    reference: datetime | None = None,
) -> tuple[str, int]:
    """Reset the current-month counter automatically after month changes."""

    active_month_key = current_month_key(reference)
    if stored_month_key != active_month_key:
        return active_month_key, 0
    return active_month_key, max(count, 0)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None

    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _string_or_none(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _ensure_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _sanitize_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in ("-", "_", ".") else "_" for char in value)
