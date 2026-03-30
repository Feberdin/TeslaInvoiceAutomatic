"""Local filesystem helper for watched Tesla PDF invoices.

Purpose:
    Find PDF files in a configured watch directory and read them safely for
    email delivery.
Input/Output:
    Accepts local directory paths and returns normalized invoice file objects or
    raw PDF bytes.
Important invariants:
    Only `.pdf` files from the configured directory are considered. The helper
    fails fast on missing folders or unreadable files.
How to debug:
    If no invoices are found, first check the configured watch directory path,
    file extensions, and file permissions in Home Assistant.
"""

from __future__ import annotations

from pathlib import Path

from .errors import InvoiceDownloadError
from .models import InvoicePdfFile, build_invoice_pdf_file


class LocalInvoicePdfClient:
    """Client for reading locally downloaded Tesla invoice PDFs."""

    def list_invoice_files(self, watch_directory: Path) -> list[InvoicePdfFile]:
        """Return all PDF files from the watch directory, newest first."""

        if not watch_directory.exists():
            raise InvoiceDownloadError(
                f"Der Ueberwachungsordner existiert nicht: {watch_directory}. "
                "Bitte den Pfad in der Integration pruefen."
            )
        if not watch_directory.is_dir():
            raise InvoiceDownloadError(
                f"Der konfigurierte PDF-Pfad ist kein Ordner: {watch_directory}."
            )

        pdf_paths = sorted(
            (
                path
                for path in watch_directory.iterdir()
                if path.is_file() and path.suffix.lower() == ".pdf"
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return [build_invoice_pdf_file(path) for path in pdf_paths]

    def read_invoice_pdf(self, pdf_path: Path) -> bytes:
        """Read one local PDF file or raise a clear error."""

        try:
            data = pdf_path.read_bytes()
        except OSError as err:
            raise InvoiceDownloadError(
                f"PDF-Datei konnte nicht gelesen werden: {pdf_path}. Fehler: {err}"
            ) from err

        if not data:
            raise InvoiceDownloadError(
                f"PDF-Datei ist leer und kann nicht versendet werden: {pdf_path}"
            )
        return data
