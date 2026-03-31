"""Persistent state storage for processed Tesla invoice PDFs.

Purpose:
    Remember which Tesla invoice content IDs were already emailed so the
    integration does not resend the same official PDF after every restart or
    polling cycle.
Input/Output:
    Reads and writes Home Assistant storage records under one stable key.
Important invariants:
    `processed_invoice_ids` is append-only in normal operation; duplicates are
    removed while preserving deterministic order.
How to debug:
    Inspect the stored state file in Home Assistant's `.storage` directory and
    compare it with the Tesla `contentId` values returned by the charging
    history endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION


@dataclass(slots=True)
class IntegrationState:
    """Persistent integration state."""

    processed_invoice_ids: list[str] = field(default_factory=list)
    last_invoice_id: str | None = None
    last_session_id: str | None = None
    last_downloaded_file: str | None = None
    last_email_at: str | None = None
    last_error: str | None = None
    last_history_import_at: str | None = None
    last_history_days: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "IntegrationState":
        """Build one state object from storage data."""

        if not raw:
            return cls()

        return cls(
            processed_invoice_ids=list(dict.fromkeys(raw.get("processed_invoice_ids", []))),
            last_invoice_id=raw.get("last_invoice_id"),
            last_session_id=raw.get("last_session_id"),
            last_downloaded_file=raw.get("last_downloaded_file"),
            last_email_at=raw.get("last_email_at"),
            last_error=raw.get("last_error"),
            last_history_import_at=raw.get("last_history_import_at"),
            last_history_days=raw.get("last_history_days"),
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize state for Home Assistant storage."""

        return {
            "processed_invoice_ids": list(dict.fromkeys(self.processed_invoice_ids)),
            "last_invoice_id": self.last_invoice_id,
            "last_session_id": self.last_session_id,
            "last_downloaded_file": self.last_downloaded_file,
            "last_email_at": self.last_email_at,
            "last_error": self.last_error,
            "last_history_import_at": self.last_history_import_at,
            "last_history_days": self.last_history_days,
        }


class TeslaInvoiceStore:
    """Thin wrapper around Home Assistant's Store helper."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}_{entry_id}",
            private=True,
            atomic_writes=True,
        )

    async def async_load(self) -> IntegrationState:
        """Load persisted state from disk."""

        data = await self._store.async_load()
        return IntegrationState.from_dict(data)

    async def async_save(self, state: IntegrationState) -> None:
        """Persist state to disk."""

        await self._store.async_save(state.as_dict())
