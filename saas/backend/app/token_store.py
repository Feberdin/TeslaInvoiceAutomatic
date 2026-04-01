"""
Purpose: Encrypt Tesla access and refresh tokens before they are written to the database.
Input/Output: Accepts plain tokens and returns encrypted strings prefixed with `enc::`, or reverses that process when reading.
Invariants: The configured `SECRET_KEY` must stay stable; otherwise previously stored Tesla tokens can no longer be decrypted.
Debug: If Tesla auth breaks after a secret change, inspect whether stored values still start with `enc::` and whether the current `SECRET_KEY` matches the one used during import.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.errors import TeslaAuthenticationError


ENCRYPTED_PREFIX = "enc::"


def _build_fernet() -> Fernet:
    settings = get_settings()
    derived_key = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived_key))


def encrypt_secret(value: str | None) -> str | None:
    """Encrypt one token before persistence.

    Example:
        encrypt_secret("abc") -> "enc::gAAAAA..."
    """

    normalized_value = (value or "").strip()
    if not normalized_value:
        return None
    if normalized_value.startswith(ENCRYPTED_PREFIX):
        return normalized_value
    encrypted_value = _build_fernet().encrypt(normalized_value.encode("utf-8")).decode("utf-8")
    return f"{ENCRYPTED_PREFIX}{encrypted_value}"


def decrypt_secret(value: str | None) -> str | None:
    """Return the plain token and accept legacy unencrypted values for upgrades."""

    normalized_value = (value or "").strip()
    if not normalized_value:
        return None
    if not normalized_value.startswith(ENCRYPTED_PREFIX):
        return normalized_value
    encrypted_payload = normalized_value.removeprefix(ENCRYPTED_PREFIX)
    try:
        return _build_fernet().decrypt(encrypted_payload.encode("utf-8")).decode("utf-8")
    except InvalidToken as err:
        raise TeslaAuthenticationError(
            "Gespeicherte Tesla-Tokens konnten nicht entschluesselt werden. "
            "Bitte die Tesla-Verbindung erneut speichern und darauf achten, dass `SECRET_KEY` nicht gewechselt hat."
        ) from err
