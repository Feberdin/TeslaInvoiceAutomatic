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

import sys
import unittest

from tests._module_loader import load_integration_module

const = load_integration_module("const")
load_integration_module("errors")
load_integration_module("models")
emailer = load_integration_module("emailer")

CONF_RECIPIENT_EMAIL = const.CONF_RECIPIENT_EMAIL
CONF_SENDER_EMAIL = const.CONF_SENDER_EMAIL
CONF_SMTP_HOST = const.CONF_SMTP_HOST
CONF_SMTP_PORT = const.CONF_SMTP_PORT
EmailDeliveryError = sys.modules[
    "custom_components.tesla_invoice_automatic.errors"
].EmailDeliveryError
validate_email_config = emailer.validate_email_config


class ValidateEmailConfigTests(unittest.TestCase):
    """Validate the minimum SMTP configuration contract."""

    def test_validate_email_config_accepts_minimum_valid_values(self) -> None:
        validate_email_config(
            {
                CONF_SMTP_HOST: "smtp.example.org",
                CONF_SMTP_PORT: 587,
                CONF_SENDER_EMAIL: "tesla@example.org",
                CONF_RECIPIENT_EMAIL: "archive@example.org",
            }
        )

    def test_validate_email_config_rejects_missing_required_fields(self) -> None:
        with self.assertRaises(EmailDeliveryError) as error:
            validate_email_config({CONF_SMTP_HOST: "smtp.example.org"})

        self.assertIn(CONF_SMTP_PORT, str(error.exception))
        self.assertIn(CONF_SENDER_EMAIL, str(error.exception))
        self.assertIn(CONF_RECIPIENT_EMAIL, str(error.exception))


if __name__ == "__main__":
    unittest.main()
