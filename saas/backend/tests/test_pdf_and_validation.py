"""
Purpose: Verify that PDF generation and e-mail validation work without external dependencies.
Input/Output: Feeds known text and addresses into the helper modules and checks their outputs.
Invariants: Demo PDFs always start with `%PDF`, invalid e-mail addresses fail with a clear error.
Debug: If downloads or recipient validation break, reproduce the smallest failing case in these tests first.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pdf_utils import generate_demo_invoice_pdf
from app.utils import validate_email_address, validate_recipient_list


class PdfAndValidationTests(unittest.TestCase):
    def test_generates_pdf_header(self) -> None:
        pdf_bytes = generate_demo_invoice_pdf(["Demo Invoice", "Amount: 19.99 EUR"])
        self.assertTrue(pdf_bytes.startswith(b"%PDF-1.4"))
        self.assertIn(b"Demo Invoice", pdf_bytes)

    def test_validates_email_addresses(self) -> None:
        self.assertEqual("user@example.com", validate_email_address(" User@example.com "))

    def test_rejects_invalid_recipient_list(self) -> None:
        with self.assertRaises(ValueError):
            validate_recipient_list(["valid@example.com", "not-an-email"])


if __name__ == "__main__":
    unittest.main()
