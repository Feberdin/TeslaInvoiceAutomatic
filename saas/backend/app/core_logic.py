"""
Purpose: Hold dependency-free business logic that can be tested without FastAPI, SQLAlchemy or Docker.
Input/Output: Accepts charging sessions and known invoice IDs, returns only the truly new invoice candidates.
Invariants: Existing invoices are never duplicated, output order matches the original session order.
Debug: If duplicate invoices appear, start by checking `existing_invoice_ids` and this module's selection result.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.domain import ChargingSession, InvoiceCandidate


def build_new_invoice_candidates(
    sessions: Sequence[ChargingSession],
    existing_invoice_ids: Iterable[str],
) -> tuple[list[InvoiceCandidate], int]:
    """Return only sessions with invoice IDs that are not known yet."""

    known_invoice_ids = set(existing_invoice_ids)
    created_candidates: list[InvoiceCandidate] = []
    skipped_count = 0

    # The sync flow keeps processing order stable so the dashboard stays easy to reason about.
    for session in sessions:
        if session.invoice_id in known_invoice_ids:
            skipped_count += 1
            continue

        created_candidates.append(
            InvoiceCandidate(
                invoice_id=session.invoice_id,
                started_at=session.started_at,
                amount=session.amount,
                currency=session.currency,
                location=session.location,
            )
        )
        known_invoice_ids.add(session.invoice_id)

    return created_candidates, skipped_count

