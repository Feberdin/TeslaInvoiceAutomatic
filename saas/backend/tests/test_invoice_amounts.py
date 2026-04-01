"""
Purpose: Verify the PDF/text amount extraction fallback for already downloaded Tesla invoices.
Input/Output: Uses small text snippets to confirm amount and currency extraction without needing real PDFs.
Invariants: The parser should prefer summary lines such as `Gesamtbetrag` and never invent amounts from empty text.
Debug: If live invoices still show `unbekannt`, reproduce the text fragment here before touching runtime sync code.
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.invoice_amounts import extract_amount_and_currency_from_text


class InvoiceAmountExtractionTests(unittest.TestCase):
    def test_prefers_summary_line_with_currency_suffix(self) -> None:
        text = """
        Tesla, Inc.
        Ladevorgang Hamburg Stillhorn
        Energiemenge 42,50 kWh
        Gesamtbetrag 28,90 EUR
        """

        amount, currency = extract_amount_and_currency_from_text(text)

        self.assertEqual(Decimal("28.90"), amount)
        self.assertEqual("EUR", currency)

    def test_supports_currency_prefix_amounts(self) -> None:
        text = """
        Invoice total
        EUR 19.75
        """

        amount, currency = extract_amount_and_currency_from_text(text)

        self.assertEqual(Decimal("19.75"), amount)
        self.assertEqual("EUR", currency)

    def test_returns_none_for_empty_text(self) -> None:
        amount, currency = extract_amount_and_currency_from_text("")

        self.assertIsNone(amount)
        self.assertIsNone(currency)


if __name__ == "__main__":
    unittest.main()
