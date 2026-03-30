"""Tests for SMTP configuration validation.

Purpose:
    Check the most important failure paths before any real SMTP connection is
    attempted in Home Assistant.
Input/Output:
    Passes small config dictionaries into the validation helper.
Important invariants:
    Missing required fields must fail fast with a clear message.
How to debug:
    If one test fails, inspect the exact missing field list in the thrown
    `EmailDeliveryError`.
"""

import pytest

from custom_components.tesla_invoice_automatic.const import (
    CONF_RECIPIENT_EMAIL,
    CONF_SENDER_EMAIL,
    CONF_SMTP_HOST,
    CONF_SMTP_PORT,
)
from custom_components.tesla_invoice_automatic.emailer import validate_email_config
from custom_components.tesla_invoice_automatic.errors import EmailDeliveryError


def test_validate_email_config_accepts_minimum_valid_values() -> None:
    validate_email_config(
        {
            CONF_SMTP_HOST: "smtp.example.org",
            CONF_SMTP_PORT: 587,
            CONF_SENDER_EMAIL: "tesla@example.org",
            CONF_RECIPIENT_EMAIL: "archive@example.org",
        }
    )


def test_validate_email_config_rejects_missing_required_fields() -> None:
    with pytest.raises(EmailDeliveryError) as error:
        validate_email_config({CONF_SMTP_HOST: "smtp.example.org"})

    assert CONF_SMTP_PORT in str(error.value)
    assert CONF_SENDER_EMAIL in str(error.value)
    assert CONF_RECIPIENT_EMAIL in str(error.value)
