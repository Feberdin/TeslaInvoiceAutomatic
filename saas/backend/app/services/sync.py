"""
Purpose: Orchestrate invoice discovery, deduplication, PDF storage and mail logging.
Input/Output: Reads users, accounts and vehicles from the DB and writes newly found invoices back.
Invariants: Each invoice ID is stored only once, sync updates account timestamps, mail is sent only for new invoices.
Debug: If invoices do not appear, inspect the logged sync summary and the candidate list produced in this service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core_logic import build_new_invoice_candidates
from app.domain import SyncSummary
from app.models import EmailSetting, Invoice, TeslaAccount, User, Vehicle
from app.services.emailer import ConsoleEmailService
from app.services.storage import LocalFileStorage
from app.services.tesla import DemoTeslaClient


logger = logging.getLogger(__name__)


@dataclass
class RuntimeServices:
    tesla_client: DemoTeslaClient
    storage: LocalFileStorage
    emailer: ConsoleEmailService


class InvoiceSyncService:
    def __init__(self, db: Session, runtime_services: RuntimeServices) -> None:
        self.db = db
        self.runtime_services = runtime_services

    def sync_user(self, user: User, *, manual_demo_invoice: bool = False) -> SyncSummary:
        accounts = list(user.tesla_accounts)
        if not accounts:
            raise ValueError(
                f"Für {user.email} ist noch kein Tesla-Konto verbunden. Bitte zuerst die Demo-Verbindung anlegen."
            )

        created_invoices: list[Invoice] = []
        skipped_total = 0
        fresh_seed = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") if manual_demo_invoice else None

        # Each vehicle is synced independently so failures remain local and easier to debug.
        for account in accounts:
            for vehicle in list(account.vehicles):
                sessions = self.runtime_services.tesla_client.list_recent_sessions(
                    account,
                    vehicle,
                    fresh_seed=fresh_seed,
                )
                existing_invoice_ids = self.db.scalars(
                    select(Invoice.invoice_id).where(Invoice.vehicle_id == vehicle.id)
                ).all()
                new_candidates, skipped_count = build_new_invoice_candidates(sessions, existing_invoice_ids)
                skipped_total += skipped_count

                for candidate in new_candidates:
                    pdf_bytes = self.runtime_services.tesla_client.download_invoice_pdf(
                        candidate.invoice_id,
                        vehicle,
                        Decimal(candidate.amount),
                        candidate.currency,
                        candidate.location,
                    )
                    pdf_path = self.runtime_services.storage.save_invoice_pdf(candidate.invoice_id, pdf_bytes)
                    invoice = Invoice(
                        invoice_id=candidate.invoice_id,
                        user_id=user.id,
                        vehicle_id=vehicle.id,
                        amount=float(candidate.amount),
                        currency=candidate.currency,
                        charge_started_at=candidate.started_at,
                        location=candidate.location,
                        pdf_path=pdf_path,
                        source="demo",
                    )
                    self.db.add(invoice)
                    created_invoices.append(invoice)

            account.last_synced_at = datetime.now(timezone.utc)

        self.db.commit()

        emailed_recipients: list[str] = []
        email_settings = user.email_settings
        if created_invoices and email_settings and email_settings.recipients_csv:
            recipients = [item.strip() for item in email_settings.recipients_csv.split(",") if item.strip()]
            subject = email_settings.subject_template.format(email=user.email, count=len(created_invoices))
            body = (
                f"Es wurden {len(created_invoices)} neue Demo-Rechnungen fuer {user.email} verarbeitet. "
                f"Die PDFs liegen im Datenverzeichnis und koennen im Dashboard heruntergeladen werden."
            )
            attachments = [invoice.pdf_path for invoice in created_invoices if email_settings.attach_pdf]
            self.runtime_services.emailer.send_summary(recipients, subject, body, attachments)
            emailed_recipients = recipients

        logger.info(
            "Invoice sync finished for %s: created=%s skipped=%s emailed=%s",
            user.email,
            len(created_invoices),
            skipped_total,
            emailed_recipients,
        )
        return SyncSummary(
            created_count=len(created_invoices),
            skipped_count=skipped_total,
            emailed_recipients=emailed_recipients,
        )

    def sync_all_users(self) -> list[tuple[str, SyncSummary]]:
        users = self.db.scalars(select(User)).all()
        summaries: list[tuple[str, SyncSummary]] = []

        for user in users:
            if not user.tesla_accounts:
                continue
            summary = self.sync_user(user)
            summaries.append((user.email, summary))

        return summaries


def ensure_email_settings(db: Session, user: User) -> EmailSetting:
    if user.email_settings is None:
        user.email_settings = EmailSetting(user_id=user.id, recipients_csv="")
        db.add(user.email_settings)
        db.commit()
        db.refresh(user)
    return user.email_settings


def ensure_user(db: Session, email: str) -> User:
    existing_user = db.scalar(select(User).where(User.email == email))
    if existing_user is not None:
        return existing_user

    user = User(email=email, subscription_plan="basic")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def serialize_invoice(invoice: Invoice, app_base_url: str) -> dict[str, object]:
    return {
        "invoice_id": invoice.invoice_id,
        "amount": float(invoice.amount),
        "currency": invoice.currency,
        "location": invoice.location,
        "charge_started_at": invoice.charge_started_at,
        "vehicle_name": invoice.vehicle.nickname if invoice.vehicle else "Tesla",
        "pdf_download_url": f"{app_base_url}/api/v1/invoices/{invoice.invoice_id}/download",
    }

