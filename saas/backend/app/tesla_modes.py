"""
Purpose: Centralize the selection and labeling logic for Tesla connection modes.
Input/Output: Accepts simple account-like objects with a `mode` attribute and returns a stable mode order or selected account.
Invariants: `auto` prefers the official Fleet path, the unofficial owner-token path stays available, and unknown values never silently change behavior.
Debug: If the dashboard shows the wrong active Tesla source, inspect `normalize_preferred_live_sync_mode` and `select_live_account` first.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar


PREFERRED_LIVE_SYNC_MODES = ("auto", "fleet_oauth", "owner_api")
LIVE_TESLA_ACCOUNT_MODES = ("fleet_oauth", "owner_api")
MODE_LABELS = {
    "auto": "Automatisch",
    "fleet_oauth": "Fleet API",
    "owner_api": "Inoffizieller Token-Import",
    "demo": "Demo-Fallback",
    "none": "Noch offen",
}


class SupportsTeslaMode(Protocol):
    mode: str


AccountType = TypeVar("AccountType", bound=SupportsTeslaMode)


def normalize_preferred_live_sync_mode(value: str | None) -> str:
    normalized = (value or "auto").strip().lower()
    if normalized not in PREFERRED_LIVE_SYNC_MODES:
        raise ValueError(
            "Unbekannter Tesla-Live-Modus. Erlaubt sind nur `auto`, `fleet_oauth` oder `owner_api`."
        )
    return normalized


def live_mode_priority(preferred_mode: str | None) -> tuple[str, ...]:
    normalized = normalize_preferred_live_sync_mode(preferred_mode)
    if normalized == "owner_api":
        return ("owner_api", "fleet_oauth")
    return ("fleet_oauth", "owner_api")


def select_live_account(accounts: Sequence[AccountType], preferred_mode: str | None) -> AccountType | None:
    """Pick the best live Tesla account for the current user preference.

    Example:
        - preferred mode is `owner_api`
        - both owner and fleet tokens are stored
        - the unofficial owner-token path wins until the user changes the preference again
    """

    for mode in live_mode_priority(preferred_mode):
        for account in accounts:
            if account.mode == mode:
                return account
    return None


def connected_live_modes(accounts: Sequence[SupportsTeslaMode]) -> list[str]:
    return [mode for mode in LIVE_TESLA_ACCOUNT_MODES if any(account.mode == mode for account in accounts)]


def mode_label(mode: str) -> str:
    return MODE_LABELS.get(mode, "Tesla")
