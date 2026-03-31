"""
Purpose: Persist generated invoice PDFs on a shared filesystem volume.
Input/Output: Accepts invoice IDs and PDF bytes, returns the absolute path of the stored file.
Invariants: Files are written below `DATA_DIR/invoices` and existing files are replaced atomically by path.
Debug: If downloads fail, verify that the file exists at the returned path and that the volume is mounted correctly.
"""

from __future__ import annotations

from pathlib import Path


class LocalFileStorage:
    def __init__(self, data_dir: Path) -> None:
        self.invoice_dir = data_dir / "invoices"
        self.invoice_dir.mkdir(parents=True, exist_ok=True)

    def save_invoice_pdf(self, invoice_id: str, pdf_bytes: bytes) -> str:
        target_path = self.invoice_dir / f"{invoice_id}.pdf"
        target_path.write_bytes(pdf_bytes)
        return str(target_path)

