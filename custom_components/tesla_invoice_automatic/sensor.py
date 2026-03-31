"""Sensor platform for Tesla invoice automation status.

Purpose:
    Expose both live status and longer-term operating metrics in Home
    Assistant, so operators can immediately see whether invoice collection and
    email delivery are healthy.
Input/Output:
    Reads coordinator data and renders multiple diagnostic and statistics
    sensors for dashboards, automations, and troubleshooting.
Important invariants:
    The primary status sensor remains available even when the last update
    failed; detailed failure context is exposed as attributes and companion
    sensors.
How to debug:
    Inspect the status sensor plus the timestamp/count sensors in Developer
    Tools > States and compare them with the integration logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_CONSECUTIVE_FAILURES,
    ATTR_INVOICES_SENT_THIS_MONTH,
    ATTR_INVOICES_SENT_TOTAL,
    ATTR_LAST_DOWNLOADED_FILE,
    ATTR_LAST_EMAIL_AT,
    ATTR_LAST_ERROR,
    ATTR_LAST_FETCH_ATTEMPT_AT,
    ATTR_LAST_FETCH_DURATION_SECONDS,
    ATTR_LAST_HISTORY_DAYS,
    ATTR_LAST_HISTORY_IMPORT_AT,
    ATTR_LAST_INVOICE_ID,
    ATTR_LAST_RUN_PROCESSED_COUNT,
    ATTR_LAST_RUN_STATUS,
    ATTR_LAST_SESSION_ID,
    ATTR_LAST_SUCCESSFUL_FETCH_AT,
    ATTR_LINKED_TESLA_HA,
    ATTR_PENDING_INVOICE_COUNT,
    DEFAULT_NAME,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import TeslaInvoiceCoordinator
from .models import ProcessingResult


@dataclass(frozen=True, kw_only=True)
class TeslaInvoiceSensorDescription(SensorEntityDescription):
    """Describe one secondary Tesla Invoice sensor."""

    value_fn: Callable[[ProcessingResult], Any]


SENSOR_DESCRIPTIONS: tuple[TeslaInvoiceSensorDescription, ...] = (
    TeslaInvoiceSensorDescription(
        key="last_successful_fetch",
        name="Last Successful Fetch",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _parse_timestamp(data.last_successful_fetch_at),
    ),
    TeslaInvoiceSensorDescription(
        key="last_invoice_sent",
        name="Last Invoice Sent",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _parse_timestamp(data.last_email_at),
    ),
    TeslaInvoiceSensorDescription(
        key="pending_invoices",
        name="Pending Invoices",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:file-document-multiple-outline",
        value_fn=lambda data: data.pending_invoice_count,
    ),
    TeslaInvoiceSensorDescription(
        key="invoices_sent_total",
        name="Invoices Sent Total",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:counter",
        value_fn=lambda data: data.invoices_sent_total,
    ),
    TeslaInvoiceSensorDescription(
        key="invoices_sent_this_month",
        name="Invoices Sent This Month",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:calendar-month-outline",
        value_fn=lambda data: data.invoices_sent_this_month,
    ),
    TeslaInvoiceSensorDescription(
        key="consecutive_failures",
        name="Consecutive Failures",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
        value_fn=lambda data: data.consecutive_failures,
    ),
    TeslaInvoiceSensorDescription(
        key="last_fetch_duration_seconds",
        name="Last Fetch Duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:timer-outline",
        value_fn=lambda data: data.last_fetch_duration_seconds,
    ),
    TeslaInvoiceSensorDescription(
        key="last_run_processed_count",
        name="Last Run Processed Invoices",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:email-fast-outline",
        value_fn=lambda data: data.last_run_processed_count,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tesla invoice sensors for one config entry."""

    coordinator: TeslaInvoiceCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        TeslaInvoiceStatusSensor(coordinator, entry.title or DEFAULT_NAME),
    ]
    entities.extend(
        TeslaInvoiceMetricSensor(coordinator, entry.title or DEFAULT_NAME, description)
        for description in SENSOR_DESCRIPTIONS
    )
    async_add_entities(entities)


class TeslaInvoiceBaseSensor(CoordinatorEntity[TeslaInvoiceCoordinator], SensorEntity):
    """Shared device metadata for all Tesla Invoice sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TeslaInvoiceCoordinator, entry_title: str) -> None:
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.config_entry.entry_id)},
            "manufacturer": MANUFACTURER,
            "name": entry_title,
        }


class TeslaInvoiceStatusSensor(TeslaInvoiceBaseSensor):
    """Primary sensor summarizing the latest fetch outcome."""

    _attr_name = "Status"
    _attr_icon = "mdi:file-document-check-outline"

    def __init__(self, coordinator: TeslaInvoiceCoordinator, entry_title: str) -> None:
        super().__init__(coordinator, entry_title)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_status"

    @property
    def native_value(self) -> str:
        """Return the latest fetch status, not just the last send action."""

        return self.coordinator.data.last_run_status or "idle"

    @property
    def extra_state_attributes(self) -> dict[str, str | int | float | None]:
        """Expose detailed troubleshooting and summary data."""

        return {
            ATTR_LAST_INVOICE_ID: self.coordinator.data.last_invoice_id,
            ATTR_LAST_SESSION_ID: self.coordinator.data.last_session_id,
            ATTR_LAST_EMAIL_AT: self.coordinator.data.last_email_at,
            ATTR_LAST_ERROR: self.coordinator.data.last_error,
            ATTR_LAST_DOWNLOADED_FILE: self.coordinator.data.last_downloaded_file,
            ATTR_PENDING_INVOICE_COUNT: self.coordinator.data.pending_invoice_count,
            ATTR_LAST_HISTORY_IMPORT_AT: self.coordinator.data.last_history_import_at,
            ATTR_LAST_HISTORY_DAYS: self.coordinator.data.last_history_days,
            ATTR_LINKED_TESLA_HA: self.coordinator.linked_title,
            ATTR_LAST_FETCH_ATTEMPT_AT: self.coordinator.data.last_fetch_attempt_at,
            ATTR_LAST_SUCCESSFUL_FETCH_AT: self.coordinator.data.last_successful_fetch_at,
            ATTR_LAST_FETCH_DURATION_SECONDS: self.coordinator.data.last_fetch_duration_seconds,
            ATTR_LAST_RUN_STATUS: self.coordinator.data.last_run_status,
            ATTR_LAST_RUN_PROCESSED_COUNT: self.coordinator.data.last_run_processed_count,
            ATTR_INVOICES_SENT_TOTAL: self.coordinator.data.invoices_sent_total,
            ATTR_INVOICES_SENT_THIS_MONTH: self.coordinator.data.invoices_sent_this_month,
            ATTR_CONSECUTIVE_FAILURES: self.coordinator.data.consecutive_failures,
        }


class TeslaInvoiceMetricSensor(TeslaInvoiceBaseSensor):
    """Generic numeric/timestamp companion sensor."""

    entity_description: TeslaInvoiceSensorDescription

    def __init__(
        self,
        coordinator: TeslaInvoiceCoordinator,
        entry_title: str,
        description: TeslaInvoiceSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry_title)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the current metric value from the coordinator snapshot."""

        return self.entity_description.value_fn(self.coordinator.data)


def _parse_timestamp(value: str | None) -> datetime | None:
    """Convert stored ISO strings into datetime objects for HA timestamp sensors."""

    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
