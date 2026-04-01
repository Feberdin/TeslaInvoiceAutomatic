"""
Purpose: Define project-specific exceptions for Tesla, Google and delivery flows.
Input/Output: Lower-level services raise these errors so routes and workers can turn them into clear user feedback.
Invariants: Messages should explain what failed, why it likely failed and what the operator should inspect next.
Debug: Start by checking the exact exception class because it tells you whether the problem is user input, auth, API reachability or file handling.
"""

from __future__ import annotations


class TeslaInvoiceAutomaticError(Exception):
    """Base error for the SaaS service."""


class TeslaApiError(TeslaInvoiceAutomaticError):
    """Raised when Tesla's charging endpoints return an unexpected response."""


class TeslaAuthenticationError(TeslaInvoiceAutomaticError):
    """Raised when Tesla credentials are missing, expired or rejected."""


class InvoiceDownloadError(TeslaInvoiceAutomaticError):
    """Raised when an invoice PDF cannot be downloaded or validated."""


class TeslaTokenImportError(TeslaInvoiceAutomaticError):
    """Raised when imported Tesla cache or token payloads are incomplete."""


class GoogleAuthenticationError(TeslaInvoiceAutomaticError):
    """Raised when Google OAuth or a stored Google token is missing, expired or rejected."""


class GoogleApiError(TeslaInvoiceAutomaticError):
    """Raised when Google userinfo or Gmail API calls fail unexpectedly."""


class EmailDeliveryError(TeslaInvoiceAutomaticError):
    """Raised when Gmail, SMTP or a local delivery precondition blocks sending a message."""
