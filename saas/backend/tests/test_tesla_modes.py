"""
Purpose: Verify the preference logic between Fleet API and the unofficial owner-token path.
Input/Output: Uses lightweight fake account objects instead of the database or FastAPI routes.
Invariants: `auto` prefers Fleet, an explicit owner preference wins when both live modes exist, and invalid preference values are rejected early.
Debug: If the dashboard highlights the wrong Tesla source, reproduce the failing preference combination here first.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tesla_modes import connected_live_modes, normalize_preferred_live_sync_mode, select_live_account


class TeslaModeTests(unittest.TestCase):
    def test_auto_prefers_fleet_when_both_accounts_exist(self) -> None:
        accounts = [
            SimpleNamespace(mode="owner_api"),
            SimpleNamespace(mode="fleet_oauth"),
        ]

        selected = select_live_account(accounts, "auto")

        self.assertIsNotNone(selected)
        self.assertEqual("fleet_oauth", selected.mode)

    def test_explicit_owner_preference_wins_when_both_accounts_exist(self) -> None:
        accounts = [
            SimpleNamespace(mode="owner_api"),
            SimpleNamespace(mode="fleet_oauth"),
        ]

        selected = select_live_account(accounts, "owner_api")

        self.assertIsNotNone(selected)
        self.assertEqual("owner_api", selected.mode)

    def test_connected_live_modes_are_reported_in_stable_order(self) -> None:
        accounts = [
            SimpleNamespace(mode="demo"),
            SimpleNamespace(mode="owner_api"),
            SimpleNamespace(mode="fleet_oauth"),
        ]

        self.assertEqual(["fleet_oauth", "owner_api"], connected_live_modes(accounts))

    def test_invalid_preference_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_preferred_live_sync_mode("unsupported")


if __name__ == "__main__":
    unittest.main()
