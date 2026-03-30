"""Tests for invoice parsing and pending-session selection.

Purpose:
    Verify the pure business logic that decides which Tesla charging sessions
    still need invoice processing.
Input/Output:
    Uses synthetic Tesla API payloads and asserts deterministic parsed results.
Important invariants:
    Only sessions with both session ID and invoice ID are eligible, and already
    processed invoice IDs must be filtered out.
How to debug:
    Run `pytest -q` and compare the failing payload field names with the parser
    expectations in `models.py`.
"""

from datetime import datetime, timezone

from custom_components.tesla_invoice_automatic.models import (
    filter_sessions_by_age,
    parse_charging_history,
    select_pending_sessions,
)


def test_parse_charging_history_sorts_newest_first() -> None:
    payload = {
        "data": [
            {
                "chargeSessionId": "older-session",
                "invoiceId": "inv-older",
                "chargeStopDateTime": "2026-03-29T10:00:00Z",
            },
            {
                "chargeSessionId": "newer-session",
                "invoiceId": "inv-newer",
                "chargeStopDateTime": "2026-03-30T12:00:00Z",
            },
        ]
    }

    sessions = parse_charging_history(payload)

    assert [session.invoice_id for session in sessions] == ["inv-newer", "inv-older"]


def test_parse_charging_history_skips_items_without_invoice_or_session() -> None:
    payload = {
        "data": [
            {"chargeSessionId": "missing-invoice"},
            {"invoiceId": "missing-session"},
            {"chargeSessionId": "ok", "invoiceId": "inv-ok"},
        ]
    }

    sessions = parse_charging_history(payload)

    assert len(sessions) == 1
    assert sessions[0].session_id == "ok"
    assert sessions[0].invoice_id == "inv-ok"


def test_select_pending_sessions_filters_processed_invoice_ids() -> None:
    sessions = parse_charging_history(
        {
            "data": [
                {"chargeSessionId": "s1", "invoiceId": "inv-1"},
                {"chargeSessionId": "s2", "invoiceId": "inv-2"},
            ]
        }
    )

    pending = select_pending_sessions(sessions, {"inv-2"})

    assert [session.invoice_id for session in pending] == ["inv-1"]


def test_filter_sessions_by_age_keeps_only_requested_window() -> None:
    sessions = parse_charging_history(
        {
            "data": [
                {
                    "chargeSessionId": "old",
                    "invoiceId": "inv-old",
                    "chargeStopDateTime": "2025-01-01T12:00:00Z",
                },
                {
                    "chargeSessionId": "recent",
                    "invoiceId": "inv-recent",
                    "chargeStopDateTime": "2026-03-15T12:00:00Z",
                },
            ]
        }
    )

    filtered = filter_sessions_by_age(
        sessions,
        days_back=30,
        now=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert [session.invoice_id for session in filtered] == ["inv-recent"]
