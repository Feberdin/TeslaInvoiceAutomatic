"""Config flow for Tesla Invoice Automatic.

Purpose:
    Configure a local watch folder plus SMTP settings so manually downloaded
    Tesla PDFs can be forwarded automatically.
Input/Output:
    Receives operator input from the Home Assistant UI and stores validated
    config-entry data.
Important invariants:
    The watch directory must be an absolute path that Home Assistant can read.
How to debug:
    If setup fails, verify the folder path, PDF file permissions, and SMTP
    values first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_FILE_PATTERN,
    CONF_POLL_INTERVAL_MINUTES,
    CONF_RECIPIENT_EMAIL,
    CONF_SENDER_EMAIL,
    CONF_SMTP_HOST,
    CONF_SMTP_PASSWORD,
    CONF_SMTP_PORT,
    CONF_SMTP_SECURITY,
    CONF_SMTP_USERNAME,
    CONF_WATCH_DIRECTORY,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DEFAULT_SMTP_PORT,
    DOMAIN,
    SMTP_SECURITY_OPTIONS,
)


def _build_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Create one reusable config schema for setup and options."""

    data = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_WATCH_DIRECTORY, default=data.get(CONF_WATCH_DIRECTORY, "")): str,
            vol.Required(CONF_FILE_PATTERN, default=data.get(CONF_FILE_PATTERN, "*.pdf")): str,
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
    )


class TeslaInvoiceAutomaticConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow implementation."""

    VERSION = 3

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial setup step."""

        errors: dict[str, str] = {}
        if user_input is not None:
            watch_directory = Path(user_input[CONF_WATCH_DIRECTORY].strip())
            if not user_input[CONF_WATCH_DIRECTORY].strip():
                errors[CONF_WATCH_DIRECTORY] = "required"
            elif not watch_directory.is_absolute():
                errors[CONF_WATCH_DIRECTORY] = "absolute_path"
            elif not user_input[CONF_RECIPIENT_EMAIL].strip():
                errors[CONF_RECIPIENT_EMAIL] = "required"
            elif not user_input[CONF_SMTP_HOST].strip():
                errors[CONF_SMTP_HOST] = "required"
            else:
                await self.async_set_unique_id(str(watch_directory))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Tesla PDFs {watch_directory.name}",
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
