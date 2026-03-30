"""Domain models and pure helpers for local PDF invoice processing.

Purpose:
    Represent PDF files from a watched folder and decide which ones still need
    to be emailed.
Input/Output:
    Receives filesystem metadata and returns normalized Python objects.
Important invariants:
    A file is uniquely identified by a stable signature derived from name,
    size, and modification time so re-sends stay deterministic.
How to debug:
    If a PDF is skipped unexpectedly, compare its generated `file_id` with the
    IDs stored in Home Assistant storage for this integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(slots=True)
class InvoicePdfFile:
    """Normalized representation of one local PDF file."""

    file_id: str
    file_name: str
    file_path: Path
    modified_at: datetime
    size_bytes: int


@dataclass(slots=True)
class ProcessingResult:
    """Summary exposed by the coordinator after one processing pass."""

    processed_invoice_ids: list[str]
    last_invoice_id: str | None
    last_session_id: str | None
    last_downloaded_file: str | None
    last_email_at: str | None
    last_error: str | None
    pending_invoice_count: int
    last_history_import_at: str | None = None
    last_history_days: int | None = None


def build_invoice_pdf_file(path: Path) -> InvoicePdfFile:
    """Create one normalized PDF object from a filesystem path."""

    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    file_id = f"{path.name}:{stat.st_size}:{int(stat.st_mtime_ns)}"
    return InvoicePdfFile(
        file_id=file_id,
        file_name=path.name,
        file_path=path,
        modified_at=modified_at,
        size_bytes=stat.st_size,
    )


def select_pending_files(
    files: list[InvoicePdfFile],
    processed_file_ids: set[str],
) -> list[InvoicePdfFile]:
    """Return only files that have not been emailed yet."""

    return [item for item in files if item.file_id not in processed_file_ids]


def filter_files_by_age(
    files: list[InvoicePdfFile],
    *,
    days_back: int,
    now: datetime | None = None,
) -> list[InvoicePdfFile]:
    """Return files inside the requested historical import window."""

    if days_back <= 0:
        return list(files)

    reference_now = now or datetime.now(timezone.utc)
    cutoff = reference_now - timedelta(days=days_back)
    return [item for item in files if item.modified_at >= cutoff]
