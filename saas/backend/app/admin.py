"""
Purpose: Centralize operator-only access checks so the dashboard and admin menu use the same rule.
Input/Output: Accepts normalized user e-mails together with global settings and returns a simple boolean decision.
Invariants: Admin access is explicit via `ADMIN_EMAILS`; normal end-user accounts never gain operator rights implicitly.
Debug: If the Admin-Menue does not appear, inspect `ADMIN_EMAILS`, the normalized login e-mail and these helper functions first.
"""

from __future__ import annotations

from app.config import Settings
from app.utils import normalize_email


def user_is_admin(settings: Settings, email: str | None) -> bool:
    """Return whether the given user e-mail is allowed to open the operator-only admin area."""

    if not email:
        return False
    normalized_email = normalize_email(email)
    return normalized_email in settings.admin_emails
