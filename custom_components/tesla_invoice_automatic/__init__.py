"""Home Assistant setup for Tesla Invoice Automatic.

Purpose:
    Register the integration, initialize shared services, and coordinate
    lifecycle management for each config entry.
Input/Output:
    Home Assistant calls these functions during setup, unload, and service use.
Important invariants:
    Each config entry watches one local folder containing manually downloaded
    Tesla PDFs.
How to debug:
    If setup fails, verify the folder path and SMTP settings first.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
import voluptuous as vol

from .const import (
    CONF_WATCH_DIRECTORY,
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

    if not entry.data.get(CONF_WATCH_DIRECTORY):
        raise ValueError(
            "Diese Konfiguration stammt aus einer aelteren Version. Bitte die "
            "Integration entfernen und mit dem PDF-Ueberwachungsordner neu anlegen."
        )

    store = TeslaInvoiceStore(hass, entry.entry_id)
    coordinator = TeslaInvoiceCoordinator(hass, entry, store)
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
