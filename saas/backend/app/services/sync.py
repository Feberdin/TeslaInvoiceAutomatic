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
from app.invoice_amounts import extract_amount_and_currency_from_pdf_bytes, extract_amount_and_currency_from_pdf_path
from app.models import EmailSetting, Invoice, TeslaAccount, User, Vehicle
from app.services.emailer import DeliveryEmailService
from app.services.tesla_fleet import TeslaFleetApiClient
from app.services.storage import LocalFileStorage
from app.services.tesla import DemoTeslaClient
from app.services.tesla_owner import TeslaOwnerApiClient
from app.tesla_modes import mode_label, select_live_account


logger = logging.getLogger(__name__)
settings = get_settings()
IMPLEMENTED_ACCOUNTING_TARGETS = {"Circula"}
CIRCULA_RECEIPT_ADDRESS = "receipts@in.circula.com"


@dataclass
class RuntimeServices:
    demo_tesla_client: DemoTeslaClient
    owner_tesla_client: TeslaOwnerApiClient
    fleet_tesla_client: TeslaFleetApiClient
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
                existing_invoices = self.db.scalars(
                    select(Invoice).where(Invoice.vehicle_id == vehicle.id)
                ).all()
                repaired_existing = self._refresh_existing_invoice_metadata(existing_invoices, sessions)
                if repaired_existing:
                    logger.info(
                        "Repaired stored invoice metadata for %s on %s. repaired=%s",
                        user.email,
                        vehicle.vin,
                        repaired_existing,
                    )
                new_candidates, skipped_count = build_new_invoice_candidates(
                    sessions,
                    {invoice.invoice_id for invoice in existing_invoices},
                )
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
                    resolved_amount = Decimal(candidate.amount)
                    resolved_currency = candidate.currency
                    if resolved_amount <= 0:
                        pdf_amount, pdf_currency = extract_amount_and_currency_from_pdf_bytes(pdf_bytes)
                        if pdf_amount is not None and pdf_amount > 0:
                            resolved_amount = pdf_amount
                            resolved_currency = pdf_currency or resolved_currency
                    pdf_path = self.runtime_services.storage.save_invoice_pdf(candidate.invoice_id, pdf_bytes)
                    invoice = Invoice(
                        invoice_id=candidate.invoice_id,
                        user_id=user.id,
                        vehicle_id=vehicle.id,
                        amount=float(resolved_amount),
                        currency=resolved_currency,
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
        selected_targets = {
            item.strip() for item in (email_settings.accounting_targets_csv or "").split(",") if item.strip()
        } if email_settings else set()
        if created_invoices and email_settings and (email_settings.recipients_csv or "Circula" in selected_targets):
            recipients = [item.strip() for item in email_settings.recipients_csv.split(",") if item.strip()]
            subject = email_settings.subject_template.format(email=user.email, count=len(created_invoices))
            source_label = mode_label(sync_mode)
            body = (
                f"Es wurden {len(created_invoices)} neue Rechnungen ueber {source_label} "
                f"fuer {user.email} verarbeitet. "
                f"Die PDFs liegen im Datenverzeichnis und koennen im Dashboard heruntergeladen werden."
            )
            target_recipients, cc_recipients, from_email, attachments = self._resolve_delivery_targets(
                email_settings,
                created_invoices,
                recipients,
            )
            delivery_mode = self.runtime_services.emailer.send_summary(
                target_recipients,
                subject,
                body,
                attachments,
                from_email=from_email,
                cc_recipients=cc_recipients,
            )
            emailed_recipients = [*target_recipients, *cc_recipients]

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

    def _refresh_existing_invoice_metadata(
        self,
        existing_invoices: list[Invoice],
        sessions: list,
    ) -> int:
        """Repair old invoice rows with fresh Tesla history data or stored PDF totals."""

        sessions_by_invoice_id = {session.invoice_id: session for session in sessions}
        repaired_count = 0

        for invoice in existing_invoices:
            updated = False
            session = sessions_by_invoice_id.get(invoice.invoice_id)
            if session is not None:
                updated = self._apply_invoice_metadata(
                    invoice,
                    amount=session.amount,
                    currency=session.currency,
                    location=session.location,
                )

            if self._invoice_amount_decimal(invoice) <= 0:
                pdf_amount, pdf_currency = extract_amount_and_currency_from_pdf_path(invoice.pdf_path)
                updated = self._apply_invoice_metadata(
                    invoice,
                    amount=pdf_amount,
                    currency=pdf_currency,
                    location=None,
                ) or updated

            if updated:
                repaired_count += 1

        return repaired_count

    def _resolve_delivery_targets(
        self,
        email_settings: EmailSetting,
        created_invoices: list[Invoice],
        recipients: list[str],
    ) -> tuple[list[str], list[str], str | None, list[str]]:
        selected_targets = {
            item.strip() for item in (email_settings.accounting_targets_csv or "").split(",") if item.strip()
        }
        attach_pdf = email_settings.attach_pdf or "Circula" in selected_targets
        attachments = [invoice.pdf_path for invoice in created_invoices if attach_pdf]
        if "Circula" not in selected_targets or not created_invoices:
            return recipients, [], None, attachments

        if not email_settings.employee_sender_email:
            raise ValueError(
                "Circula ist aktiviert, aber es fehlt die Mitarbeiter-Absenderadresse. "
                "Bitte in den Versand-Einstellungen `Mitarbeiter-E-Mail fuer Circula` setzen."
            )

        return [CIRCULA_RECEIPT_ADDRESS], recipients, email_settings.employee_sender_email, attachments

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
        live_account = select_live_account(list(user.tesla_accounts), getattr(user, "preferred_live_sync_mode", "auto"))
        if live_account is not None:
            return [live_account], live_account.mode

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
        if account.mode == "fleet_oauth":
            return self.runtime_services.fleet_tesla_client.list_recent_sessions(account, vehicle.vin)
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
        if account.mode == "fleet_oauth":
            return self.runtime_services.fleet_tesla_client.download_invoice_pdf(account, invoice_id)
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

    def _apply_invoice_metadata(
        self,
        invoice: Invoice,
        *,
        amount: Decimal | None,
        currency: str | None,
        location: str | None,
    ) -> bool:
        """Update a stored invoice only when better metadata is available."""

        updated = False
        current_amount = self._invoice_amount_decimal(invoice)
        if amount is not None and amount > 0 and current_amount <= 0:
            invoice.amount = float(amount)
            updated = True

        normalized_currency = (currency or "").strip().upper()
        if normalized_currency and (not invoice.currency or invoice.currency.strip().upper() != normalized_currency):
            invoice.currency = normalized_currency
            updated = True

        normalized_location = (location or "").strip()
        if normalized_location and (not invoice.location or invoice.location == "Tesla Supercharger"):
            invoice.location = normalized_location
            updated = True

        return updated

    def _invoice_amount_decimal(self, invoice: Invoice) -> Decimal:
        try:
            return Decimal(str(invoice.amount or 0))
        except Exception:
            logger.warning("Stored invoice amount could not be parsed. invoice_id=%s", invoice.invoice_id)
            return Decimal("0.00")

    def _store_last_error(self, user_id: int, message: str) -> None:
        accounts = self.db.scalars(select(TeslaAccount).where(TeslaAccount.user_id == user_id)).all()
        for account in accounts:
            if account.mode in {"owner_api", "fleet_oauth"}:
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
