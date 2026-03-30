"""Sensor platform for Tesla invoice automation status.

Purpose:
    Expose the latest processing status in Home Assistant so operators can see
    whether invoice collection and email delivery are healthy.
Input/Output:
    Reads coordinator data and renders one sensor entity with useful attributes.
Important invariants:
    The sensor remains available even when the last update failed; the error is
    stored as an attribute instead of hiding state.
How to debug:
    Inspect the sensor attributes in Developer Tools > States and compare them
    with the integration logs when an invoice is missing.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_LAST_DOWNLOADED_FILE,
    ATTR_LAST_EMAIL_AT,
    ATTR_LAST_ERROR,
    ATTR_LAST_HISTORY_DAYS,
    ATTR_LAST_HISTORY_IMPORT_AT,
    ATTR_LAST_INVOICE_ID,
    ATTR_LAST_SESSION_ID,
    ATTR_PENDING_INVOICE_COUNT,
    ATTR_WATCH_DIRECTORY,
    CONF_WATCH_DIRECTORY,
    DEFAULT_NAME,
    MANUFACTURER,
)
from .coordinator import TeslaInvoiceCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tesla invoice status sensor for one config entry."""

    coordinator: TeslaInvoiceCoordinator = hass.data["tesla_invoice_automatic"][entry.entry_id]
    async_add_entities([TeslaInvoiceStatusSensor(coordinator, entry.title or DEFAULT_NAME)])


class TeslaInvoiceStatusSensor(CoordinatorEntity[TeslaInvoiceCoordinator], SensorEntity):
    """Single sensor summarizing the last invoice processing result."""

    _attr_has_entity_name = True
    _attr_name = "Status"

    def __init__(self, coordinator: TeslaInvoiceCoordinator, entry_title: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_status"
        self._attr_device_info = {
            "identifiers": {("tesla_invoice_automatic", coordinator.config_entry.entry_id)},
            "manufacturer": MANUFACTURER,
            "name": entry_title,
        }

    @property
    def native_value(self) -> str:
        """Return a compact state that is easy to read in dashboards."""

        if self.coordinator.data.last_error:
            return "error"
        if self.coordinator.data.last_invoice_id:
            return "sent"
        return "idle"

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        """Expose detailed troubleshooting data for operators."""

        return {
            ATTR_LAST_INVOICE_ID: self.coordinator.data.last_invoice_id,
            ATTR_LAST_SESSION_ID: self.coordinator.data.last_session_id,
            ATTR_LAST_EMAIL_AT: self.coordinator.data.last_email_at,
            ATTR_LAST_ERROR: self.coordinator.data.last_error,
            ATTR_LAST_DOWNLOADED_FILE: self.coordinator.data.last_downloaded_file,
            ATTR_PENDING_INVOICE_COUNT: self.coordinator.data.pending_invoice_count,
            ATTR_LAST_HISTORY_IMPORT_AT: self.coordinator.data.last_history_import_at,
            ATTR_LAST_HISTORY_DAYS: self.coordinator.data.last_history_days,
            ATTR_WATCH_DIRECTORY: self.coordinator.runtime_config.get(CONF_WATCH_DIRECTORY),
        }
