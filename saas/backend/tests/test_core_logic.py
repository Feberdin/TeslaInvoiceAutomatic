"""
Purpose: Test the invoice deduplication logic independently from FastAPI or the database.
Input/Output: Creates demo charging sessions and validates the produced invoice candidates.
Invariants: Duplicate invoice IDs are skipped and new invoices keep their original order.
Debug: If sync creates duplicates, reproduce the case here before changing runtime code.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core_logic import build_new_invoice_candidates
from app.domain import ChargingSession


class BuildNewInvoiceCandidatesTests(unittest.TestCase):
    def test_skips_existing_invoice_ids_and_keeps_new_order(self) -> None:
        now = datetime.now(timezone.utc)
        sessions = [
            ChargingSession("inv-001", now, Decimal("12.50"), "EUR", "Berlin"),
            ChargingSession("inv-002", now, Decimal("15.50"), "EUR", "Hamburg"),
            ChargingSession("inv-001", now, Decimal("12.50"), "EUR", "Berlin"),
            ChargingSession("inv-003", now, Decimal("18.20"), "EUR", "Munich"),
        ]

        candidates, skipped_count = build_new_invoice_candidates(sessions, {"inv-000", "inv-002"})

        self.assertEqual(["inv-001", "inv-003"], [candidate.invoice_id for candidate in candidates])
        self.assertEqual(2, skipped_count)


if __name__ == "__main__":
    unittest.main()
