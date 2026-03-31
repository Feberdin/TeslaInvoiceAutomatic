"""Integration-specific exceptions for user-friendly diagnostics.

Purpose:
    Make failure reasons explicit so logs and Home Assistant repairs are easier
    to understand than generic network or SMTP stack traces.
Input/Output:
    Raised by lower-level modules and handled by the coordinator or setup code.
Important invariants:
    Error messages should help the operator understand what failed and which
    configuration value to inspect next.
How to debug:
    Read the exact exception class in the log first; it tells you whether to
    inspect Tesla auth, invoice history/download, storage, or SMTP settings.
"""


class TeslaInvoiceAutomaticError(Exception):
    """Base integration error."""


class TeslaApiError(TeslaInvoiceAutomaticError):
    """Raised when Tesla mobile ownership endpoints return an unexpected response."""


class TeslaAuthenticationError(TeslaInvoiceAutomaticError):
    """Raised when the linked Tesla owner login is missing or rejected."""


class InvoiceDownloadError(TeslaInvoiceAutomaticError):
    """Raised when a PDF invoice cannot be found, downloaded, or saved."""


class EmailDeliveryError(TeslaInvoiceAutomaticError):
    """Raised when SMTP delivery fails."""
