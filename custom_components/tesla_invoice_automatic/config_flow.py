"""Config flow for Tesla Invoice Automatic.

Purpose:
    Let operators configure Tesla API and SMTP access through the Home
    Assistant UI with early validation and understandable field names.
Input/Output:
    Receives form data from the UI and stores validated config-entry values.
Important invariants:
    Required fields are checked before entry creation so runtime failures become
    rarer and easier to understand.
How to debug:
    If the flow refuses to continue, inspect the shown field errors first, then
    Home Assistant logs for deeper validation details.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_API_BASE_URL,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DOWNLOAD_TIMEOUT_SECONDS,
    CONF_POLL_INTERVAL_MINUTES,
    CONF_RECIPIENT_EMAIL,
    CONF_REFRESH_TOKEN,
    CONF_SENDER_EMAIL,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSWORD,
    CONF_SMTP_PORT,
    CONF_SMTP_SECURITY,
    CONF_SMTP_USERNAME,
    CONF_TOKEN_URL,
    CONF_VIN,
    DEFAULT_API_BASE_URL,
    DEFAULT_NAME,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DEFAULT_SMTP_PORT,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TOKEN_URL,
    DOMAIN,
    SMTP_SECURITY_OPTIONS,
)


def _build_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Create one reusable config schema for setup and options."""

    data = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_VIN, default=data.get(CONF_VIN, "")): str,
            vol.Required(CONF_ACCESS_TOKEN, default=data.get(CONF_ACCESS_TOKEN, "")): str,
            vol.Optional(CONF_REFRESH_TOKEN, default=data.get(CONF_REFRESH_TOKEN, "")): str,
            vol.Optional(CONF_CLIENT_ID, default=data.get(CONF_CLIENT_ID, "")): str,
            vol.Optional(CONF_CLIENT_SECRET, default=data.get(CONF_CLIENT_SECRET, "")): str,
            vol.Required(CONF_API_BASE_URL, default=data.get(CONF_API_BASE_URL, DEFAULT_API_BASE_URL)): str,
            vol.Required(CONF_TOKEN_URL, default=data.get(CONF_TOKEN_URL, DEFAULT_TOKEN_URL)): str,
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
            vol.Required(
                CONF_DOWNLOAD_TIMEOUT_SECONDS,
                default=data.get(CONF_DOWNLOAD_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=300)),
        }
    )


class TeslaInvoiceAutomaticConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow implementation."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial setup step."""

        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_VIN].strip():
                errors[CONF_VIN] = "required"
            elif not user_input[CONF_ACCESS_TOKEN].strip():
                errors[CONF_ACCESS_TOKEN] = "required"
            elif not user_input[CONF_RECIPIENT_EMAIL].strip():
                errors[CONF_RECIPIENT_EMAIL] = "required"
            elif not user_input[CONF_SMTP_HOST].strip():
                errors[CONF_SMTP_HOST] = "required"
            else:
                await self.async_set_unique_id(user_input[CONF_VIN].strip())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Tesla {user_input[CONF_VIN].strip()}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input),
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
            return self.async_create_entry(title="", data=user_input)

        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(defaults),
            errors={},
        )
