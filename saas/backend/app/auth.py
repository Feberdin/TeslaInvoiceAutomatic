"""
Purpose: Provide password hashing and session helpers for the simple SaaS login flow.
Input/Output: Accepts plain-text passwords and request sessions, returns secure hashes and user IDs.
Invariants: Passwords are never stored in plain text, and session state contains only the numeric user ID.
Debug: If logins fail unexpectedly, verify the stored hash format and the `user_id` value in the session cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request


PBKDF2_ITERATIONS = 390_000


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${password_hash}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False

    try:
        algorithm, raw_iterations, salt, stored_digest = stored_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    calculated_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        int(raw_iterations),
    ).hex()
    return hmac.compare_digest(calculated_digest, stored_digest)


def validate_password_strength(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Das Passwort muss mindestens 8 Zeichen lang sein.")
    return password


def set_session_user(request: "Request", user_id: int) -> None:
    request.session["user_id"] = user_id


def clear_session_user(request: "Request") -> None:
    request.session.clear()


def get_session_user_id(request: "Request") -> int:
    from fastapi import HTTPException

    user_id = request.session.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Bitte zuerst einloggen.")
    return user_id
