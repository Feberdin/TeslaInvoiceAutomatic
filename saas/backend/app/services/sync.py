"""
Purpose: Orchestrate invoice discovery, deduplication, PDF storage and mail delivery for demo and live Tesla accounts.
Input/Output: Reads users, Tesla accounts and vehicles from the DB and writes only newly found invoices back.
Invariants: Each invoice ID is stored only once, sync updates account timestamps, real Tesla accounts take priority over demo accounts and mail is sent only for newly created invoices.
Debug: If invoices do not appear, inspect the selected sync mode, the candidate list and the `last_error` field on the active Tesla account before changing UI code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core_logic import build_new_invoice_candidates
from app.config import get_settings
from app.domain import SyncSummary
from app.errors import InvoiceDownloadError, TeslaApiError, TeslaAuthenticationError
from app.models import EmailSetting, Invoice, TeslaAccount, User, Vehicle
from app.services.emailer import DeliveryEmailService
from app.services.storage import LocalFileStorage
from app.services.tesla import DemoTeslaClient
from app.services.tesla_owner import TeslaOwnerApiClient


logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class RuntimeServices:
    demo_tesla_client: DemoTeslaClient
    owner_tesla_client: TeslaOwnerApiClient
    storage: LocalFileStorage
    emailer: DeliveryEmailService


class InvoiceSyncService:
    def __init__(self, db: Session, runtime_services: RuntimeServices) -> None:
        self.db = db
        self.runtime_services = runtime_services

    def sync_user(self, user: User, *, manual_demo_invoice: bool = False) -> SyncSummary:
        accounts, sync_mode = self._resolve_sync_accounts(user)
        if not accounts:
            raise ValueError(
                f"Fuer {user.email} ist noch kein synchronisierbares Tesla-Konto vorbereitet. "
                "Bitte zuerst Tesla verbinden oder mindestens eine Demo-VIN anlegen."
            )
        if not any(account.vehicles for account in accounts):
            if sync_mode == "owner_api":
                raise ValueError(
                    "Fuer den verbundenen Tesla-Zugang ist noch keine VIN hinterlegt. "
                    "Bitte zuerst mindestens eine echte VIN speichern."
                )
            raise ValueError(
                "Bitte zuerst mindestens eine VIN anlegen, bevor du Rechnungen testen kannst."
            )

        created_invoices: list[Invoice] = []
        skipped_total = 0
        fresh_seed = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") if manual_demo_invoice else None

        # Each vehicle is synced independently so failures remain local and easier to debug.
        for account in accounts:
            if not account.vehicles:
                continue

            for vehicle in list(account.vehicles):
                sessions = self._list_recent_sessions(
                    account,
                    vehicle,
                    fresh_seed=fresh_seed if sync_mode == "demo" else None,
                )
                existing_invoice_ids = self.db.scalars(
                    select(Invoice.invoice_id).where(Invoice.vehicle_id == vehicle.id)
                ).all()
                new_candidates, skipped_count = build_new_invoice_candidates(sessions, existing_invoice_ids)
                skipped_total += skipped_count

                for candidate in new_candidates:
                    pdf_bytes = self._download_invoice_pdf(
                        account,
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
                        source=sync_mode,
                    )
                    self.db.add(invoice)
                    created_invoices.append(invoice)

            account.last_synced_at = datetime.now(timezone.utc)
            account.last_error = None

        self.db.commit()

        emailed_recipients: list[str] = []
        delivery_mode = "none"
        email_settings = user.email_settings
        if created_invoices and email_settings and email_settings.recipients_csv:
            recipients = [item.strip() for item in email_settings.recipients_csv.split(",") if item.strip()]
            subject = email_settings.subject_template.format(email=user.email, count=len(created_invoices))
            body = (
                f"Es wurden {len(created_invoices)} neue {'Tesla-' if sync_mode == 'owner_api' else 'Demo-'}Rechnungen "
                f"fuer {user.email} verarbeitet. "
                f"Die PDFs liegen im Datenverzeichnis und koennen im Dashboard heruntergeladen werden."
            )
            attachments = [invoice.pdf_path for invoice in created_invoices if email_settings.attach_pdf]
            delivery_mode = self.runtime_services.emailer.send_summary(recipients, subject, body, attachments)
            emailed_recipients = recipients

        logger.info(
            "Invoice sync finished for %s: mode=%s created=%s skipped=%s emailed=%s delivery_mode=%s",
            user.email,
            sync_mode,
            len(created_invoices),
            skipped_total,
            emailed_recipients,
            delivery_mode,
        )
        return SyncSummary(
            created_count=len(created_invoices),
            skipped_count=skipped_total,
            emailed_recipients=emailed_recipients,
            delivery_mode=delivery_mode,
            sync_mode=sync_mode,
        )

    def sync_all_users(self) -> list[tuple[str, SyncSummary]]:
        users = self.db.scalars(select(User)).all()
        summaries: list[tuple[str, SyncSummary]] = []

        for user in users:
            try:
                accounts, _ = self._resolve_sync_accounts(user)
                if not accounts:
                    continue
                summary = self.sync_user(user)
                summaries.append((user.email, summary))
            except (ValueError, TeslaAuthenticationError, TeslaApiError, InvoiceDownloadError) as exc:
                self.db.rollback()
                self._store_last_error(user.id, str(exc))
                logger.exception("Sync fuer %s ist fehlgeschlagen: %s", user.email, exc)

        return summaries

    def _resolve_sync_accounts(self, user: User) -> tuple[list[TeslaAccount], str]:
        owner_accounts = [account for account in user.tesla_accounts if account.mode == "owner_api"]
        if owner_accounts:
            return owner_accounts, "owner_api"

        demo_accounts = [account for account in user.tesla_accounts if account.mode == "demo"]
        if demo_accounts and settings.demo_mode:
            return demo_accounts, "demo"

        return [], "none"

    def _list_recent_sessions(
        self,
        account: TeslaAccount,
        vehicle: Vehicle,
        *,
        fresh_seed: str | None,
    ):
        if account.mode == "owner_api":
            return self.runtime_services.owner_tesla_client.list_recent_sessions(account, vehicle)
        return self.runtime_services.demo_tesla_client.list_recent_sessions(
            account,
            vehicle,
            fresh_seed=fresh_seed,
        )

    def _download_invoice_pdf(
        self,
        account: TeslaAccount,
        invoice_id: str,
        vehicle: Vehicle,
        amount: Decimal,
        currency: str,
        location: str,
    ) -> bytes:
        if account.mode == "owner_api":
            return self.runtime_services.owner_tesla_client.download_invoice_pdf(
                account,
                invoice_id,
                vehicle,
                amount,
                currency,
                location,
            )
        return self.runtime_services.demo_tesla_client.download_invoice_pdf(
            invoice_id,
            vehicle,
            amount,
            currency,
            location,
        )

    def _store_last_error(self, user_id: int, message: str) -> None:
        accounts = self.db.scalars(select(TeslaAccount).where(TeslaAccount.user_id == user_id)).all()
        for account in accounts:
            if account.mode == "owner_api":
                account.last_error = message
        self.db.commit()


def ensure_email_settings(db: Session, user: User, *, default_recipient: str | None = None) -> EmailSetting:
    if user.email_settings is None:
        recipients_csv = default_recipient or ""
        user.email_settings = EmailSetting(
            user_id=user.id,
            recipients_csv=recipients_csv,
            accounting_targets_csv="",
        )
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
        "source": invoice.source,
    }
