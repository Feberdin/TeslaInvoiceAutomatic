"""
Purpose: Provide a traceable demo mail delivery mechanism without external SMTP dependencies.
Input/Output: Writes a JSON-like log line into `email-outbox.log` instead of sending real e-mail.
Invariants: Every recorded message contains recipients, subject and referenced attachment paths.
Debug: If sync says an e-mail was sent, the first place to verify it is the outbox log file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class ConsoleEmailService:
    def __init__(self, data_dir: Path, default_from_email: str) -> None:
        self.outbox_path = data_dir / "email-outbox.log"
        self.default_from_email = default_from_email
        self.outbox_path.parent.mkdir(parents=True, exist_ok=True)

    def send_summary(self, recipients: list[str], subject: str, body: str, attachment_paths: list[str]) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        record = (
            f"[{timestamp}] from={self.default_from_email} "
            f"to={','.join(recipients)} subject={subject!r} "
            f"attachments={attachment_paths!r} body={body!r}\n"
        )
        self.outbox_path.write_text(self.outbox_path.read_text() + record if self.outbox_path.exists() else record)

