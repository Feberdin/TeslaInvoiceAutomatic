"""Config flow for Tesla Invoice Automatic.

Purpose:
    Configure SMTP delivery and link this integration to an existing `tesla_ha`
    setup, so Tesla login only has to be done once.
Input/Output:
    Receives operator input from the Home Assistant UI and stores validated
    config-entry data.
Important invariants:
    At least one configured `tesla_ha` entry must exist, because its TeslaPy
    cache is reused for authentication.
How to debug:
    If setup aborts, first ensure the `tesla_ha` integration is installed and
    logged in successfully. This integration depends on it.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_COUNTRY,
    CONF_DEVICE_LANGUAGE,
    CONF_HTTP_LOCALE,
    CONF_OWNERSHIP_BASE_URL,
    CONF_POLL_INTERVAL_MINUTES,
    CONF_RECIPIENT_EMAIL,
    CONF_SENDER_EMAIL,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSWORD,
    CONF_SMTP_PORT,
    CONF_SMTP_SECURITY,
    CONF_SMTP_USERNAME,
    CONF_TESLA_HA_ENTRY_ID,
    CONF_VIN,
    DEFAULT_DEVICE_COUNTRY,
    DEFAULT_DEVICE_LANGUAGE,
    DEFAULT_HTTP_LOCALE,
    DEFAULT_NAME,
    DEFAULT_OWNERSHIP_BASE_URL,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DEFAULT_SMTP_PORT,
    DOMAIN,
    SMTP_SECURITY_OPTIONS,
)


def _build_schema(
    hass,
    defaults: dict[str, Any] | None = None,
    *,
    include_advanced: bool,
) -> vol.Schema:
    """Create one reusable config schema for setup and options."""

    data = defaults or {}
    tesla_entries = hass.config_entries.async_entries("tesla_ha")
    options = [
        selector.SelectOptionDict(
            value=entry.entry_id,
            label=entry.title or entry.data.get("email", entry.entry_id),
        )
        for entry in tesla_entries
    ]

    schema: dict[Any, Any] = {
        vol.Required(
            CONF_TESLA_HA_ENTRY_ID,
            default=data.get(
                CONF_TESLA_HA_ENTRY_ID,
                options[0]["value"] if options else "",
            ),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(CONF_VIN, default=data.get(CONF_VIN, "")): str,
        vol.Required(CONF_RECIPIENT_EMAIL, default=data.get(CONF_RECIPIENT_EMAIL, "")): str,
        vol.Required(CONF_SENDER_EMAIL, default=data.get(CONF_SENDER_EMAIL, "")): str,
        vol.Required(CONF_SMTP_HOST, default=data.get(CONF_SMTP_HOST, "")): str,
        vol.Required(CONF_SMTP_PORT, default=data.get(CONF_SMTP_PORT, DEFAULT_SMTP_PORT)): int,
        vol.Optional(CONF_SMTP_USERNAME, default=data.get(CONF_SMTP_USERNAME, "")): str,
        vol.Optional(CONF_SMTP_PASSWORD, default=data.get(CONF_SMTP_PASSWORD, "")): str,
        vol.Required(
            CONF_SMTP_SECURITY,
            default=data.get(CONF_SMTP_SECURITY, SMTP_SECURITY_OPTIONS[0]),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=SMTP_SECURITY_OPTIONS,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(
            CONF_POLL_INTERVAL_MINUTES,
            default=data.get(CONF_POLL_INTERVAL_MINUTES, DEFAULT_POLL_INTERVAL_MINUTES),
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=720)),
    }

    if include_advanced:
        schema.update(
            {
                vol.Required(
                    CONF_DEVICE_LANGUAGE,
                    default=data.get(CONF_DEVICE_LANGUAGE, DEFAULT_DEVICE_LANGUAGE),
                ): str,
                vol.Required(
                    CONF_DEVICE_COUNTRY,
                    default=data.get(CONF_DEVICE_COUNTRY, DEFAULT_DEVICE_COUNTRY),
                ): str,
                vol.Required(
                    CONF_HTTP_LOCALE,
                    default=data.get(CONF_HTTP_LOCALE, DEFAULT_HTTP_LOCALE),
                ): str,
                vol.Required(
                    CONF_OWNERSHIP_BASE_URL,
                    default=data.get(CONF_OWNERSHIP_BASE_URL, DEFAULT_OWNERSHIP_BASE_URL),
                ): str,
            }
        )

    return vol.Schema(schema)


def _normalize_user_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Apply defaults for advanced values omitted during first setup."""

    normalized = dict(user_input)
    normalized.setdefault(CONF_DEVICE_LANGUAGE, DEFAULT_DEVICE_LANGUAGE)
    normalized.setdefault(CONF_DEVICE_COUNTRY, DEFAULT_DEVICE_COUNTRY)
    normalized.setdefault(CONF_HTTP_LOCALE, DEFAULT_HTTP_LOCALE)
    normalized.setdefault(CONF_OWNERSHIP_BASE_URL, DEFAULT_OWNERSHIP_BASE_URL)
    return normalized


def _validate_required_text_fields(user_input: dict[str, Any]) -> dict[str, str]:
    """Return per-field validation errors for the setup form."""

    errors: dict[str, str] = {}
    for key in (
        CONF_TESLA_HA_ENTRY_ID,
        CONF_VIN,
        CONF_RECIPIENT_EMAIL,
        CONF_SENDER_EMAIL,
        CONF_SMTP_HOST,
    ):
        if not str(user_input.get(key) or "").strip():
            errors[key] = "required"
    return errors


class TeslaInvoiceAutomaticConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow implementation."""

    VERSION = 4

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial setup step."""

        if not self.hass.config_entries.async_entries("tesla_ha"):
            return self.async_abort(reason="missing_tesla_ha")

        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_required_text_fields(user_input)
            if not errors:
                normalized = _normalize_user_input(user_input)
                await self.async_set_unique_id(normalized[CONF_VIN].strip())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"{DEFAULT_NAME} {normalized[CONF_VIN].strip()}",
                    data=normalized,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(
                self.hass,
                defaults=user_input,
                include_advanced=False,
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow."""

        return TeslaInvoiceAutomaticOptionsFlow(config_entry)


class TeslaInvoiceAutomaticOptionsFlow(config_entries.OptionsFlow):
    """Allow later configuration changes without deleting the entry."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Edit integration settings."""

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data=_normalize_user_input(user_input),
            )

        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(
                self.hass,
                defaults=defaults,
                include_advanced=True,
            ),
            errors={},
        )
