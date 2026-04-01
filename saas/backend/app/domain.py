"""
Purpose: Define pure-Python data structures for charging sessions and invoice drafts.
Input/Output: Services create these dataclasses, core logic transforms them without DB or web framework knowledge.
Invariants: Invoice IDs are unique identifiers, monetary amounts use `Decimal`, timestamps stay timezone-aware.
Debug: If sync behavior looks wrong, print these dataclasses before data is written to the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class ChargingSession:
    invoice_id: str
    started_at: datetime
    amount: Decimal
    currency: str
    location: str


@dataclass(frozen=True)
class InvoiceCandidate:
    invoice_id: str
    started_at: datetime
    amount: Decimal
    currency: str
    location: str


@dataclass(frozen=True)
class SyncSummary:
    created_count: int
    skipped_count: int
    emailed_recipients: list[str]
    delivery_mode: str
    sync_mode: str
