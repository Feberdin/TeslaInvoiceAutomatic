"""Domain models and small pure helpers for Tesla invoice processing.

Purpose:
    Define strongly typed objects for charging sessions and decide which session
    invoices are still pending.
Input/Output:
    Receives decoded Tesla API payloads and returns normalized Python objects.
Important invariants:
    A session is only considered processable when it has both a stable session
    ID and an invoice ID. The selector must return the newest pending invoices
    first so user-facing status is deterministic.
How to debug:
    If invoices are skipped unexpectedly, print the normalized session objects
    and compare `session_id`, `invoice_id`, and the `processed_invoice_ids`
    passed into `select_pending_sessions`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(slots=True)
class ChargingInvoiceSession:
    """Normalized representation of one Tesla charging history item."""

    session_id: str
    invoice_id: str
    charged_at: datetime | None
    location_name: str | None
    energy_added_kwh: float | None
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


def parse_charging_history(payload: dict[str, Any]) -> list[ChargingInvoiceSession]:
    """Convert Tesla charging history JSON into normalized session objects.

    Example input:
        {"data": [{"chargeSessionId": "abc", "invoiceId": "inv-1"}]}
    Example output:
        [ChargingInvoiceSession(session_id="abc", invoice_id="inv-1", ...)]
    """

    sessions: list[ChargingInvoiceSession] = []

    for item in payload.get("data", []):
        session_id = str(item.get("chargeSessionId") or item.get("sessionId") or "").strip()
        invoice_id = str(item.get("invoiceId") or item.get("invoice_id") or "").strip()
        if not session_id or not invoice_id:
            continue

        charged_at_raw = item.get("chargeStopDateTime") or item.get("endDateTime")
        charged_at = _parse_datetime(charged_at_raw)
        location_name = item.get("siteLocationName") or item.get("locationName")
        energy_value = item.get("energyAdded") or item.get("energyConsumed")
        energy_added_kwh = _parse_float(energy_value)

        sessions.append(
            ChargingInvoiceSession(
                session_id=session_id,
                invoice_id=invoice_id,
                charged_at=charged_at,
                location_name=location_name,
                energy_added_kwh=energy_added_kwh,
                raw_payload=item,
            )
        )

    sessions.sort(
        key=lambda item: item.charged_at.timestamp() if item.charged_at else 0.0,
        reverse=True,
    )
    return sessions


def select_pending_sessions(
    sessions: list[ChargingInvoiceSession],
    processed_invoice_ids: set[str],
) -> list[ChargingInvoiceSession]:
    """Return only sessions whose invoices have not been emailed yet."""

    return [session for session in sessions if session.invoice_id not in processed_invoice_ids]


def filter_sessions_by_age(
    sessions: list[ChargingInvoiceSession],
    *,
    days_back: int,
    now: datetime | None = None,
) -> list[ChargingInvoiceSession]:
    """Return sessions that fall into the requested historical import window.

    Example:
        days_back=30 keeps only sessions from the last 30 days.
    """

    if days_back <= 0:
        return list(sessions)

    reference_now = now or datetime.now(timezone.utc)
    cutoff = reference_now - timedelta(days=days_back)
    filtered: list[ChargingInvoiceSession] = []

    for session in sessions:
        if session.charged_at is None:
            filtered.append(session)
            continue

        session_time = session.charged_at
        if session_time.tzinfo is None:
            session_time = session_time.replace(tzinfo=timezone.utc)

        if session_time >= cutoff:
            filtered.append(session)

    return filtered


def _parse_datetime(value: Any) -> datetime | None:
    """Parse Tesla timestamps defensively.

    Tesla commonly returns ISO-8601 timestamps with a trailing `Z`.
    """

    if not value:
        return None

    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    """Convert numeric Tesla payload values without raising on bad inputs."""

    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None
