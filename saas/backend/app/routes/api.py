"""
Purpose: Expose JSON endpoints for demo onboarding, sync execution, invoice listing and downloads.
Input/Output: Receives browser requests from the dashboard and returns structured responses or files.
Invariants: The MVP fails fast with helpful messages when a user or Tesla account is missing.
Debug: If the dashboard stops updating, inspect the responses from these endpoints in the browser network tab.
"""

from __future__ import annotations

from datetime import datetime

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.database import get_db_session
from app.models import Invoice, TeslaAccount, User
from app.schemas import (
    DemoTeslaConnectRequest,
    EmailSettingsRequest,
    InvoiceResponse,
    ManualSyncRequest,
    StatusResponse,
    UserCreateRequest,
)
from app.services.emailer import ConsoleEmailService
from app.services.storage import LocalFileStorage
from app.services.sync import InvoiceSyncService, RuntimeServices, ensure_email_settings, ensure_user, serialize_invoice
from app.services.tesla import DemoTeslaClient
from app.utils import validate_email_address


router = APIRouter(prefix="/api/v1", tags=["api"])
settings = get_settings()


def _runtime_services() -> RuntimeServices:
    return RuntimeServices(
        tesla_client=DemoTeslaClient(),
        storage=LocalFileStorage(settings.data_dir),
        emailer=ConsoleEmailService(settings.data_dir, settings.default_from_email),
    )


def _get_user_with_relations(db: Session, email: str) -> User | None:
    return db.scalar(
        select(User)
        .where(User.email == email)
        .options(
            selectinload(User.tesla_accounts).selectinload(TeslaAccount.vehicles),
            selectinload(User.vehicles),
            selectinload(User.email_settings),
        )
    )


@router.get("/health", summary="Health endpoint for container checks")
def health() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@router.post("/demo/users", summary="Create or reuse a demo user")
def create_demo_user(payload: UserCreateRequest, db: Session = Depends(get_db_session)) -> dict[str, object]:
    user = ensure_user(db, payload.email)
    ensure_email_settings(db, user)
    return {"message": "Demo-Nutzer ist bereit.", "email": user.email}


@router.post("/demo/tesla/connect", summary="Connect a demo Tesla account")
def connect_demo_tesla(payload: DemoTeslaConnectRequest, db: Session = Depends(get_db_session)) -> dict[str, object]:
    user = ensure_user(db, payload.user_email)
    tesla_client = DemoTeslaClient()
    account, vehicles = tesla_client.provision_demo_account(db, user, payload.vehicle_count)
    db.commit()
    return {
        "message": "Demo-Tesla-Konto wurde verbunden.",
        "tesla_account_id": account.tesla_account_id,
        "vehicle_count": len(vehicles),
    }


@router.post("/settings/email", summary="Store e-mail recipients for invoice forwarding")
def save_email_settings(payload: EmailSettingsRequest, db: Session = Depends(get_db_session)) -> dict[str, object]:
    user = ensure_user(db, payload.user_email)
    email_settings = ensure_email_settings(db, user)

    # Recipient lists are stored as CSV here to keep the MVP schema and exports simple.
    email_settings.recipients_csv = ",".join(payload.recipients)
    email_settings.subject_template = payload.subject_template
    email_settings.attach_pdf = payload.attach_pdf
    db.add(email_settings)
    db.commit()

    return {"message": "E-Mail-Einstellungen gespeichert.", "recipients": payload.recipients}


@router.post("/sync/run", summary="Run invoice sync immediately")
def run_sync(payload: ManualSyncRequest, db: Session = Depends(get_db_session)) -> dict[str, object]:
    user = _get_user_with_relations(db, payload.user_email)
    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Der Nutzer wurde nicht gefunden. Bitte zuerst einen Demo-Nutzer anlegen.",
        )

    sync_service = InvoiceSyncService(db, _runtime_services())
    try:
        summary = sync_service.sync_user(user, manual_demo_invoice=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "message": "Sync wurde erfolgreich ausgeführt.",
        "created_count": summary.created_count,
        "skipped_count": summary.skipped_count,
        "emailed_recipients": summary.emailed_recipients,
    }


@router.get("/status", response_model=StatusResponse, summary="Return current dashboard status")
def get_status(
    user_email: str = Query(..., description="Demo user email"),
    db: Session = Depends(get_db_session),
) -> StatusResponse:
    normalized_email = validate_email_address(user_email)
    user = _get_user_with_relations(db, normalized_email)
    if user is None:
        return StatusResponse(
            user_exists=False,
            tesla_connected=False,
            vehicle_count=0,
            invoice_count=0,
            email_recipients=[],
            last_synced_at=None,
        )

    account = user.tesla_accounts[0] if user.tesla_accounts else None
    recipients = (
        [item.strip() for item in user.email_settings.recipients_csv.split(",") if item.strip()]
        if user.email_settings and user.email_settings.recipients_csv
        else []
    )
    invoice_count = db.query(Invoice).filter(Invoice.user_id == user.id).count()

    return StatusResponse(
        user_exists=True,
        tesla_connected=bool(user.tesla_accounts),
        vehicle_count=len(user.vehicles),
        invoice_count=invoice_count,
        email_recipients=recipients,
        last_synced_at=account.last_synced_at if account else None,
    )


@router.get("/invoices", response_model=list[InvoiceResponse], summary="List invoices for a user")
def list_invoices(
    user_email: str = Query(..., description="Demo user email"),
    db: Session = Depends(get_db_session),
) -> list[InvoiceResponse]:
    normalized_email = validate_email_address(user_email)
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None:
        return []

    invoices = db.scalars(
        select(Invoice)
        .where(Invoice.user_id == user.id)
        .options(selectinload(Invoice.vehicle))
        .order_by(Invoice.charge_started_at.desc())
    ).all()
    return [InvoiceResponse(**serialize_invoice(invoice, settings.app_base_url)) for invoice in invoices]


@router.get("/invoices/{invoice_id}/download", summary="Download a stored invoice PDF")
def download_invoice(
    invoice_id: str,
    user_email: str = Query(..., description="Demo user email for safety check"),
    db: Session = Depends(get_db_session),
) -> FileResponse:
    normalized_email = validate_email_address(user_email)
    invoice = db.scalar(
        select(Invoice)
        .join(User, Invoice.user_id == User.id)
        .where(Invoice.invoice_id == invoice_id, User.email == normalized_email)
    )
    if invoice is None:
        raise HTTPException(
            status_code=404,
            detail="Die Rechnung wurde nicht gefunden. Bitte pruefen, ob die E-Mail-Adresse zur Rechnung passt.",
        )

    pdf_path = Path(invoice.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Die Rechnungsdatei wurde in der Datenbank gefunden, aber nicht mehr auf dem Volume. "
                "Bitte Volume-Mount und data/invoices pruefen."
            ),
        )

    return FileResponse(
        path=invoice.pdf_path,
        media_type="application/pdf",
        filename=f"{invoice.invoice_id}.pdf",
    )
