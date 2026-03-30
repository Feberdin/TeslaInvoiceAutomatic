"""Tests for local PDF selection and age filtering.

Purpose:
    Verify the pure business logic that decides which locally downloaded Tesla
    PDFs still need processing.
Input/Output:
    Uses synthetic file metadata and asserts deterministic selection results.
Important invariants:
    File IDs must stay stable and already processed files must be filtered out.
How to debug:
    Run `pytest -q` and compare the generated file IDs with the persisted state.
"""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from custom_components.tesla_invoice_automatic.models import (
    build_invoice_pdf_file,
    filter_files_by_age,
    select_pending_files,
)


def test_build_invoice_pdf_file_contains_stable_metadata() -> None:
    with TemporaryDirectory() as tmp_dir:
        pdf_path = Path(tmp_dir) / "invoice.pdf"
        pdf_path.write_bytes(b"pdf-data")

        invoice_file = build_invoice_pdf_file(pdf_path)

        assert invoice_file.file_name == "invoice.pdf"
        assert invoice_file.file_path == pdf_path
        assert invoice_file.size_bytes == 8
        assert invoice_file.file_id.startswith("invoice.pdf:8:")


def test_select_pending_files_filters_processed_ids() -> None:
    with TemporaryDirectory() as tmp_dir:
        first = Path(tmp_dir) / "first.pdf"
        second = Path(tmp_dir) / "second.pdf"
        first.write_bytes(b"a")
        second.write_bytes(b"b")

        files = [build_invoice_pdf_file(first), build_invoice_pdf_file(second)]
        pending = select_pending_files(files, {files[1].file_id})

        assert [item.file_name for item in pending] == ["first.pdf"]


def test_filter_files_by_age_keeps_only_requested_window() -> None:
    with TemporaryDirectory() as tmp_dir:
        old_file = Path(tmp_dir) / "old.pdf"
        recent_file = Path(tmp_dir) / "recent.pdf"
        old_file.write_bytes(b"old")
        recent_file.write_bytes(b"recent")

        old_invoice = build_invoice_pdf_file(old_file)
        recent_invoice = build_invoice_pdf_file(recent_file)
        old_invoice.modified_at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        recent_invoice.modified_at = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

        filtered = filter_files_by_age(
            [old_invoice, recent_invoice],
            days_back=30,
            now=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
        )

        assert [item.file_name for item in filtered] == ["recent.pdf"]
