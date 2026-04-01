"""
Purpose: Expose JSON endpoints for registration, login, VIN management, invoice sync and mail testing.
Input/Output: Receives browser requests from the dashboard and returns structured responses or files.
Invariants: Authenticated routes always resolve the user from the session cookie, never from user-submitted email fields.
Debug: If the dashboard stops updating, inspect the API responses and session state before changing business logic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import clear_session_user, get_session_user_id, hash_password, set_session_user, verify_password
from app.config import get_settings
from app.database import get_db_session
from app.models import EmailSetting, Invoice, TeslaAccount, User, Vehicle
from app.pdf_utils import generate_demo_invoice_pdf
from app.schemas import (
    CurrentUserResponse,
    EmailSettingsRequest,
    InvoiceResponse,
    LoginRequest,
    ManualSyncRequest,
    RegisterRequest,
    SessionResponse,
    TestEmailRequest,
    VehicleCreateRequest,
    VehicleResponse,
)
from app.services.emailer import DeliveryEmailService
from app.services.storage import LocalFileStorage
from app.services.sync import InvoiceSyncService, RuntimeServices, ensure_email_settings, serialize_invoice
from app.services.tesla import DemoTeslaClient


router = APIRouter(prefix="/api/v1", tags=["api"])
settings = get_settings()
AVAILABLE_ACCOUNTING_TARGETS = ["DATEV", "Lexoffice", "sevDesk", "Paperless", "Dropbox", "Google Drive"]


def _runtime_services() -> RuntimeServices:
    return RuntimeServices(
        tesla_client=DemoTeslaClient(),
        storage=LocalFileStorage(settings.data_dir),
        emailer=DeliveryEmailService(settings.data_dir, settings),
    )


def _load_user(db: Session, user_id: int) -> User | None:
    return db.scalar(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.tesla_accounts).selectinload(TeslaAccount.vehicles),
            selectinload(User.vehicles),
            selectinload(User.email_settings),
        )
    )


def _get_current_user(request: Request, db: Session) -> User:
    user = _load_user(db, get_session_user_id(request))
    if user is None:
        clear_session_user(request)
        raise HTTPException(status_code=401, detail="Deine Sitzung ist abgelaufen. Bitte erneut einloggen.")
    return user


def _serialize_current_user(db: Session, user: User) -> CurrentUserResponse:
    account = user.tesla_accounts[0] if user.tesla_accounts else None
    recipients = (
        [item.strip() for item in user.email_settings.recipients_csv.split(",") if item.strip()]
        if user.email_settings and user.email_settings.recipients_csv
        else []
    )
    accounting_targets = (
        [item.strip() for item in user.email_settings.accounting_targets_csv.split(",") if item.strip()]
        if user.email_settings and user.email_settings.accounting_targets_csv
        else []
    )
    invoice_count = db.query(Invoice).filter(Invoice.user_id == user.id).count()

    return CurrentUserResponse(
        email=user.email,
        vehicle_count=len(user.vehicles),
        invoice_count=invoice_count,
        email_recipients=recipients,
        last_synced_at=account.last_synced_at if account else None,
        smtp_configured=bool(settings.smtp_host),
        subject_template=(
            user.email_settings.subject_template if user.email_settings else "Neue Tesla-Rechnungen fuer {email}"
        ),
        attach_pdf=user.email_settings.attach_pdf if user.email_settings else True,
        accounting_targets=accounting_targets,
        available_accounting_targets=AVAILABLE_ACCOUNTING_TARGETS,
        vehicles=[
            VehicleResponse(
                id=vehicle.id,
                vin=vehicle.vin,
                nickname=vehicle.nickname,
                model=vehicle.model,
            )
            for vehicle in sorted(user.vehicles, key=lambda item: item.id)
        ],
    )


@router.get("/health", summary="Health endpoint for container checks")
def health() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/auth/register", response_model=SessionResponse, summary="Register a new account")
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db_session)) -> SessionResponse:
    existing_user = db.scalar(select(User).where(User.email == payload.email))

    if existing_user and existing_user.password_hash:
        raise HTTPException(
            status_code=409,
            detail="Zu dieser E-Mail existiert bereits ein Konto. Bitte einloggen statt erneut registrieren.",
        )

    if existing_user is None:
        existing_user = User(email=payload.email, password_hash=hash_password(payload.password), subscription_plan="basic")
        db.add(existing_user)
        db.flush()
    else:
        existing_user.password_hash = hash_password(payload.password)

    email_settings = ensure_email_settings(db, existing_user, default_recipient=payload.email)
    if not email_settings.recipients_csv:
        email_settings.recipients_csv = payload.email

    db.add(existing_user)
    db.add(email_settings)
    db.commit()
    db.refresh(existing_user)

    set_session_user(request, existing_user.id)
    return SessionResponse(authenticated=True, email=existing_user.email)


@router.post("/auth/login", response_model=SessionResponse, summary="Login with e-mail and password")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db_session)) -> SessionResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Login fehlgeschlagen. Bitte E-Mail und Passwort pruefen.")

    set_session_user(request, user.id)
    return SessionResponse(authenticated=True, email=user.email)


@router.post("/auth/logout", response_model=SessionResponse, summary="Logout the current session")
def logout(request: Request) -> SessionResponse:
    clear_session_user(request)
    return SessionResponse(authenticated=False, email=None)


@router.get("/auth/session", response_model=SessionResponse, summary="Return the current session state")
def session_state(request: Request, db: Session = Depends(get_db_session)) -> SessionResponse:
    user_id = request.session.get("user_id")
    if not isinstance(user_id, int):
        return SessionResponse(authenticated=False, email=None)

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        clear_session_user(request)
        return SessionResponse(authenticated=False, email=None)

    return SessionResponse(authenticated=True, email=user.email)


@router.get("/me", response_model=CurrentUserResponse, summary="Return dashboard data for the logged-in user")
def me(request: Request, db: Session = Depends(get_db_session)) -> CurrentUserResponse:
    user = _get_current_user(request, db)
    return _serialize_current_user(db, user)


@router.post("/vehicles", response_model=VehicleResponse, summary="Add a VIN to the current account")
def add_vehicle(
    payload: VehicleCreateRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> VehicleResponse:
    user = _get_current_user(request, db)
    vehicle = DemoTeslaClient().upsert_vehicle(db, user, payload.vin, payload.nickname)
    db.commit()
    db.refresh(vehicle)
    return VehicleResponse(id=vehicle.id, vin=vehicle.vin, nickname=vehicle.nickname, model=vehicle.model)


@router.delete("/vehicles/{vehicle_id}", summary="Remove one of the current user's VINs")
def delete_vehicle(vehicle_id: int, request: Request, db: Session = Depends(get_db_session)) -> dict[str, str]:
    user = _get_current_user(request, db)
    vehicle = db.scalar(select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.user_id == user.id))
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Die angegebene VIN wurde in deinem Konto nicht gefunden.")

    db.delete(vehicle)
    db.commit()
    return {"message": "VIN wurde entfernt."}


@router.post("/settings/email", summary="Save recipients and accounting placeholders")
def save_email_settings(
    payload: EmailSettingsRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, object]:
    user = _get_current_user(request, db)
    email_settings = ensure_email_settings(db, user, default_recipient=user.email)
    email_settings.recipients_csv = ",".join(payload.recipients)
    email_settings.subject_template = payload.subject_template
    email_settings.attach_pdf = payload.attach_pdf
    email_settings.accounting_targets_csv = ",".join(
        target for target in payload.accounting_targets if target in AVAILABLE_ACCOUNTING_TARGETS
    )
    db.add(email_settings)
    db.commit()
    return {
        "message": "E-Mail- und Buchhaltungs-Einstellungen wurden gespeichert.",
        "recipients": payload.recipients,
    }


@router.post("/email/test", summary="Send a test invoice e-mail with a demo PDF")
def send_test_email(
    payload: TestEmailRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, object]:
    user = _get_current_user(request, db)
    recipients = (
        [payload.recipient_override]
        if payload.recipient_override
        else [item.strip() for item in (user.email_settings.recipients_csv if user.email_settings else "").split(",") if item.strip()]
    )
    if not recipients:
        raise HTTPException(
            status_code=400,
            detail="Bitte zuerst mindestens einen Empfänger speichern oder eine Test-E-Mail-Adresse angeben.",
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    invoice_id = f"test-mail-{timestamp}"
    storage = LocalFileStorage(settings.data_dir)
    pdf_path = storage.save_invoice_pdf(
        invoice_id,
        generate_demo_invoice_pdf(
            [
                "Tesla Invoice Automatic SaaS Testrechnung",
                f"Empfaengerkonto: {user.email}",
                f"Erstellt: {timestamp}",
                "Diese Datei dient nur dem Test des SMTP-Versands.",
            ]
        ),
    )
    delivery_mode = DeliveryEmailService(settings.data_dir, settings).send_message(
        recipients=recipients,
        subject=f"Testrechnung fuer {user.email}",
        body=(
            "Dies ist eine Testrechnung aus dem TeslaInvoiceAutomatic SaaS MVP. "
            "Wenn diese Nachricht ankommt, funktioniert dein aktueller SMTP-Pfad."
        ),
        attachment_paths=[pdf_path],
    )

    return {
        "message": "Testmail wurde verarbeitet.",
        "delivery_mode": delivery_mode,
        "recipients": recipients,
    }


@router.post("/sync/run", summary="Generate and send new demo invoices for the logged-in user")
def run_sync(
    payload: ManualSyncRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, object]:
    user = _get_current_user(request, db)
    if not user.vehicles:
        raise HTTPException(
            status_code=400,
            detail="Bitte zuerst mindestens eine VIN anlegen, bevor du Rechnungen testen kannst.",
        )

    sync_service = InvoiceSyncService(db, _runtime_services())
    try:
        summary = sync_service.sync_user(user, manual_demo_invoice=payload.include_fresh_demo_invoice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "message": "Sync wurde erfolgreich ausgeführt.",
        "created_count": summary.created_count,
        "skipped_count": summary.skipped_count,
        "emailed_recipients": summary.emailed_recipients,
        "delivery_mode": summary.delivery_mode,
    }


@router.get("/invoices", response_model=list[InvoiceResponse], summary="List invoices for the current user")
def list_invoices(request: Request, db: Session = Depends(get_db_session)) -> list[InvoiceResponse]:
    user = _get_current_user(request, db)
    invoices = db.scalars(
        select(Invoice)
        .where(Invoice.user_id == user.id)
        .options(selectinload(Invoice.vehicle))
        .order_by(Invoice.charge_started_at.desc())
    ).all()
    return [InvoiceResponse(**serialize_invoice(invoice, settings.app_base_url)) for invoice in invoices]


@router.get("/invoices/{invoice_id}/download", summary="Download a stored invoice PDF")
def download_invoice(invoice_id: str, request: Request, db: Session = Depends(get_db_session)) -> FileResponse:
    user = _get_current_user(request, db)
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_id == invoice_id, Invoice.user_id == user.id))
    if invoice is None:
        raise HTTPException(status_code=404, detail="Die Rechnung wurde in deinem Konto nicht gefunden.")

    pdf_path = Path(invoice.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Die Rechnungsdatei wurde in der Datenbank gefunden, aber nicht mehr auf dem Volume. "
                "Bitte den /data-Mount in Unraid pruefen."
            ),
        )

    return FileResponse(path=invoice.pdf_path, media_type="application/pdf", filename=f"{invoice.invoice_id}.pdf")
