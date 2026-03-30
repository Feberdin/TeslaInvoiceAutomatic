"""Home Assistant setup for Tesla Invoice Automatic.

Purpose:
    Register the integration, initialize shared services, and coordinate
    lifecycle management for each config entry.
Input/Output:
    Home Assistant calls these functions during setup, unload, and service use.
Important invariants:
    Each entry must link to an existing `tesla_ha` config entry whose Tesla
    cache can be reused for authentication.
How to debug:
    If setup fails, first verify that `tesla_ha` is installed, logged in, and
    still stores a valid Tesla cache in Home Assistant.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
import voluptuous as vol

from .const import (
    CONF_TESLA_HA_ENTRY_ID,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_HISTORY_MAX_INVOICES,
    DOMAIN,
    PLATFORMS,
    SERVICE_SEND_HISTORY,
    SERVICE_SEND_LATEST,
)
from .coordinator import TeslaInvoiceCoordinator
from .store import TeslaInvoiceStore

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up domain-level data and services."""

    hass.data.setdefault(DOMAIN, {})
    if hass.services.has_service(DOMAIN, SERVICE_SEND_LATEST):
        return True

    async def async_handle_send_latest(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        if entry_id:
            coordinator = hass.data[DOMAIN].get(entry_id)
            if coordinator:
                await coordinator.async_send_latest_invoice_now()
            return

        for coordinator in hass.data[DOMAIN].values():
            await coordinator.async_send_latest_invoice_now()

    async def async_handle_send_history(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        days_back = int(call.data.get("days_back", DEFAULT_HISTORY_DAYS))
        max_invoices = int(call.data.get("max_invoices", DEFAULT_HISTORY_MAX_INVOICES))
        include_processed = bool(call.data.get("include_processed", False))

        coordinators: list[TeslaInvoiceCoordinator]
        if entry_id:
            coordinator = hass.data[DOMAIN].get(entry_id)
            coordinators = [coordinator] if coordinator else []
        else:
            coordinators = list(hass.data[DOMAIN].values())

        for coordinator in coordinators:
            await coordinator.async_send_historical_invoices(
                days_back=days_back,
                max_invoices=max_invoices,
                include_processed=include_processed,
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_LATEST,
        async_handle_send_latest,
        schema=vol.Schema({vol.Optional("entry_id"): str}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_HISTORY,
        async_handle_send_history,
        schema=vol.Schema(
            {
                vol.Optional("entry_id"): str,
                vol.Optional("days_back", default=DEFAULT_HISTORY_DAYS): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=3650)
                ),
                vol.Optional("max_invoices", default=DEFAULT_HISTORY_MAX_INVOICES): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=500)
                ),
                vol.Optional("include_processed", default=False): bool,
            }
        ),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one config entry."""

    linked_entry_id = entry.data.get(CONF_TESLA_HA_ENTRY_ID)
    if not linked_entry_id:
        raise ConfigEntryNotReady(
            "Diese Konfiguration stammt noch aus der alten Fleet-API-Version. "
            "Bitte die Integration entfernen und mit der neuen tesla_ha-Verknuepfung "
            "neu anlegen."
        )

    linked_entry = hass.config_entries.async_get_entry(linked_entry_id)
    if linked_entry is None:
        raise ConfigEntryNotReady(
            "Die verknuepfte `tesla_ha` Integration wurde nicht gefunden."
        )

    cache_file = Path(hass.config.path(f".storage/tesla_ha_{linked_entry.entry_id}.json"))
    cache_data = linked_entry.data.get("cache")
    email = linked_entry.data.get("email")
    if not email:
        raise ConfigEntryNotReady(
            "Die verknuepfte `tesla_ha` Integration enthaelt keine Tesla-E-Mail."
        )

    def _write_cache_if_missing() -> None:
        os.makedirs(cache_file.parent, exist_ok=True)
        if cache_data and not cache_file.exists():
            with cache_file.open("w", encoding="utf-8") as handle:
                json.dump(cache_data, handle)

    await hass.async_add_executor_job(_write_cache_if_missing)

    store = TeslaInvoiceStore(hass, entry.entry_id)
    coordinator = TeslaInvoiceCoordinator(hass, entry, store, email, cache_file)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("Tesla Invoice Automatic fuer Entry %s erfolgreich gestartet.", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one config entry and its entities."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
