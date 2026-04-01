"""
Purpose: Verify password hashing and VIN validation for the SaaS login and vehicle flow.
Input/Output: Uses deterministic helper calls without touching the database or the web stack.
Invariants: Password verification only succeeds for the original password, VINs must match Tesla-style formatting.
Debug: If users cannot log in or VINs are rejected, reproduce the failing input here before changing API code.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password, validate_password_strength, verify_password
from app.utils import validate_vin


class AuthAndVinTests(unittest.TestCase):
    def test_hash_and_verify_password(self) -> None:
        password_hash = hash_password("supersecret123")
        self.assertTrue(verify_password("supersecret123", password_hash))
        self.assertFalse(verify_password("wrong-password", password_hash))

    def test_rejects_short_password(self) -> None:
        with self.assertRaises(ValueError):
            validate_password_strength("short")

    def test_validates_vin(self) -> None:
        self.assertEqual("5YJ3E1EA7JF000001", validate_vin("5yj3e1ea7jf000001"))

    def test_rejects_invalid_vin(self) -> None:
        with self.assertRaises(ValueError):
            validate_vin("123")


if __name__ == "__main__":
    unittest.main()
