"""Tests for Tesla charging-history invoice parsing.

Purpose:
    Verify the pure business logic that decides which Tesla charging invoice
    documents still need processing.
Input/Output:
    Uses synthetic Tesla API payloads and asserts deterministic parsed results.
Important invariants:
    Only invoices with `contentId`, filename, and VIN are eligible, and already
    processed content IDs must be filtered out.
How to debug:
    Run `python3 -m unittest discover -s tests -p 'test_*.py'` and compare the
    failing payload field names with the parser expectations in `models.py`.
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests._module_loader import load_integration_module

models = load_integration_module("models")

build_invoice_file_path = models.build_invoice_file_path
current_month_key = models.current_month_key
filter_invoices_by_age = models.filter_invoices_by_age
normalize_monthly_invoice_count = models.normalize_monthly_invoice_count
parse_charging_history = models.parse_charging_history
select_pending_invoices = models.select_pending_invoices


class ChargingHistoryModelTests(unittest.TestCase):
    """Exercise parser and filtering helpers with Tesla-like payloads."""

    def test_parse_charging_history_extracts_invoices_newest_first(self) -> None:
        payload = {
            "data": [
                {
                    "sessionId": "older-session",
                    "vin": "VIN1",
                    "unlatchDateTime": "2026-03-29T10:00:00Z",
                    "siteLocationName": "Hamburg",
                    "countryCode": "DE",
                    "invoices": [{"contentId": "old-id", "fileName": "old.pdf"}],
                },
                {
                    "sessionId": "newer-session",
                    "vin": "VIN1",
                    "unlatchDateTime": "2026-03-30T12:00:00Z",
                    "siteLocationName": "Berlin",
                    "countryCode": "DE",
                    "invoices": [
                        {
                            "contentId": "new-id",
                            "fileName": "new.pdf",
                            "invoiceType": "charging",
                        }
                    ],
                },
            ]
        }

        invoices = parse_charging_history(payload)

        self.assertEqual([invoice.content_id for invoice in invoices], ["new-id", "old-id"])
        self.assertEqual(invoices[0].location_name, "Berlin")
        self.assertEqual(invoices[0].invoice_type, "charging")
        self.assertEqual(invoices[0].country_code, "DE")

    def test_parse_charging_history_falls_back_to_charge_stop_timestamp(self) -> None:
        payload = {
            "data": [
                {
                    "chargeSessionId": "fallback-session",
                    "vin": "VIN1",
                    "chargeStopDateTime": "2026-03-28T09:30:00+00:00",
                    "invoices": [{"contentId": "cid-1", "fileName": "invoice.pdf"}],
                }
            ]
        }

        invoice = parse_charging_history(payload)[0]

        self.assertEqual(invoice.session_id, "fallback-session")
        self.assertEqual(
            invoice.charged_at,
            datetime(2026, 3, 28, 9, 30, tzinfo=timezone.utc),
        )

    def test_parse_charging_history_skips_invalid_invoice_entries(self) -> None:
        payload = {
            "data": [
                {
                    "sessionId": "s1",
                    "vin": "VIN1",
                    "invoices": [{"contentId": "missing-file"}, {"fileName": "missing-id.pdf"}],
                },
                {
                    "sessionId": "s2",
                    "vin": "",
                    "invoices": [{"contentId": "missing-vin", "fileName": "invalid.pdf"}],
                },
                {
                    "sessionId": "s3",
                    "vin": "VIN2",
                    "invoices": [{"contentId": "ok-id", "fileName": "ok.pdf"}],
                },
            ]
        }

        invoices = parse_charging_history(payload)

        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0].content_id, "ok-id")
        self.assertEqual(invoices[0].vin, "VIN2")

    def test_select_pending_invoices_filters_processed_ids(self) -> None:
        invoices = parse_charging_history(
            {
                "data": [
                    {"sessionId": "s1", "vin": "VIN1", "invoices": [{"contentId": "inv-1", "fileName": "a.pdf"}]},
                    {"sessionId": "s2", "vin": "VIN1", "invoices": [{"contentId": "inv-2", "fileName": "b.pdf"}]},
                ]
            }
        )

        pending = select_pending_invoices(invoices, {"inv-2"})

        self.assertEqual([invoice.content_id for invoice in pending], ["inv-1"])

    def test_filter_invoices_by_age_keeps_only_requested_window(self) -> None:
        invoices = parse_charging_history(
            {
                "data": [
                    {
                        "sessionId": "old",
                        "vin": "VIN1",
                        "unlatchDateTime": "2025-01-01T12:00:00Z",
                        "invoices": [{"contentId": "old-id", "fileName": "old.pdf"}],
                    },
                    {
                        "sessionId": "recent",
                        "vin": "VIN1",
                        "unlatchDateTime": "2026-03-15T12:00:00Z",
                        "invoices": [{"contentId": "recent-id", "fileName": "recent.pdf"}],
                    },
                    {
                        "sessionId": "undated",
                        "vin": "VIN1",
                        "invoices": [{"contentId": "undated-id", "fileName": "undated.pdf"}],
                    },
                ]
            }
        )

        filtered = filter_invoices_by_age(
            invoices,
            days_back=30,
            now=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(
            [invoice.content_id for invoice in filtered],
            ["recent-id", "undated-id"],
        )

    def test_build_invoice_file_path_creates_readable_stable_name(self) -> None:
        invoice = parse_charging_history(
            {
                "data": [
                    {
                        "sessionId": "s1",
                        "vin": "VIN1",
                        "unlatchDateTime": "2026-03-15T12:00:00Z",
                        "siteLocationName": "Berlin, Germany",
                        "invoices": [{"contentId": "cid123", "fileName": "Invoice 123.pdf"}],
                    }
                ]
            }
        )[0]

        path = build_invoice_file_path(Path("/tmp"), invoice)

        self.assertEqual(
            path.name,
            "2026-03-15--Berlin__Germany--cid123--Invoice_123.pdf",
        )

    def test_normalize_monthly_invoice_count_resets_outdated_month(self) -> None:
        month_key, count = normalize_monthly_invoice_count(
            "2026-02",
            7,
            reference=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(month_key, "2026-03")
        self.assertEqual(count, 0)

    def test_normalize_monthly_invoice_count_keeps_current_month_value(self) -> None:
        month_key, count = normalize_monthly_invoice_count(
            "2026-03",
            4,
            reference=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(month_key, "2026-03")
        self.assertEqual(count, 4)

    def test_current_month_key_uses_aware_timestamp(self) -> None:
        self.assertEqual(
            current_month_key(datetime(2026, 12, 1, 8, 0, tzinfo=timezone.utc)),
            "2026-12",
        )


if __name__ == "__main__":
    unittest.main()
