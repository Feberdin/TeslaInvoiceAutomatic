"""
Purpose: Collect small validation and formatting helpers used across API, worker and tests.
Input/Output: Accepts raw user-facing strings and returns normalized, validated values.
Invariants: E-mail addresses are always normalized to lowercase and invalid input fails fast.
Debug: If a request is rejected unexpectedly, inspect the normalized values returned by this module.
"""

from __future__ import annotations

import re
from email.utils import parseaddr


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    normalized_value = value.strip().lower()
    if not normalized_value:
        raise ValueError("Die E-Mail-Adresse darf nicht leer sein.")
    return normalized_value


def validate_email_address(value: str) -> str:
    normalized_value = normalize_email(value)
    _, parsed_address = parseaddr(normalized_value)

    if parsed_address != normalized_value or not EMAIL_PATTERN.match(normalized_value):
        raise ValueError(f"Ungültige E-Mail-Adresse: {value!r}. Bitte eine vollständige Adresse angeben.")

    return normalized_value


def validate_recipient_list(recipients: list[str]) -> list[str]:
    if not recipients:
        raise ValueError("Mindestens ein Empfänger ist erforderlich.")

    return [validate_email_address(recipient) for recipient in recipients]

