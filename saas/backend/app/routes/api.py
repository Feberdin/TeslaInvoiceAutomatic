"""
Purpose: Expose JSON endpoints for registration, login, VIN management, invoice sync and mail testing.
Input/Output: Receives browser requests from the dashboard and returns structured responses or files.
Invariants: Authenticated routes always resolve the user from the session cookie, never from user-submitted email fields.
Debug: If the dashboard stops updating, inspect the API responses and session state before changing business logic.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
from urllib import parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.admin import user_is_admin
from app.auth import clear_session_user, get_session_user_id, hash_password, set_session_user, verify_password
from app.config import get_settings
from app.database import get_db_session
from app.errors import (
    GoogleApiError,
    GoogleAuthenticationError,
    InvoiceDownloadError,
    TeslaApiError,
    TeslaAuthenticationError,
    TeslaTokenImportError,
)
from app.invoice_amounts import extract_amount_and_currency_from_pdf_path
from app.models import EmailSetting, GoogleAccount, Invoice, TeslaAccount, User, Vehicle
from app.pdf_utils import generate_demo_invoice_pdf
from app.schemas import (
    CurrentUserResponse,
    EmailSettingsRequest,
    FleetAdminStatusResponse,
    FleetKeyGenerationRequest,
    InvoiceResponse,
    LoginRequest,
    ManualSyncRequest,
    RegisterRequest,
    SessionResponse,
    TeslaConnectRequest,
    TeslaModePreferenceRequest,
    TestEmailRequest,
    VehicleCreateRequest,
    VehicleResponse,
    AdminActionResponse,
    AdminRegisteredUserResponse,
)
from app.services.emailer import DeliveryEmailService
from app.services.google_oauth import (
    GoogleOAuthClient,
    build_google_authorization_request,
    google_gmail_send_available,
    google_oauth_available,
)
from app.services.tesla_fleet import TeslaFleetApiClient, build_tesla_authorization_request, tesla_oauth_available
from app.services.tesla_partner import TeslaPartnerAdminService
from app.services.storage import LocalFileStorage
from app.services.sync import (
    IMPLEMENTED_ACCOUNTING_TARGETS,
    InvoiceSyncService,
    RuntimeServices,
    ensure_email_settings,
    serialize_invoice,
)
from app.services.tesla import DemoTeslaClient, get_preferred_user_account, get_tesla_account_by_mode, upsert_vehicle_for_account
from app.services.tesla_owner import (
    DEFAULT_DEVICE_COUNTRY,
    DEFAULT_DEVICE_LANGUAGE,
    DEFAULT_HTTP_LOCALE,
    DEFAULT_OWNERSHIP_BASE_URL,
    TeslaOwnerApiClient,
    build_imported_tokens,
)
from app.tesla_modes import connected_live_modes, normalize_preferred_live_sync_mode, select_live_account
from app.token_store import encrypt_secret


router = APIRouter(prefix="/api/v1", tags=["api"])
settings = get_settings()
AVAILABLE_ACCOUNTING_TARGETS = ["Circula", "DATEV", "Lexoffice", "sevDesk", "Paperless", "Dropbox", "Google Drive"]
GOOGLE_OAUTH_STATE_SESSION_KEY = "google_oauth_state"
GOOGLE_OAUTH_LINK_USER_ID_SESSION_KEY = "google_oauth_link_user_id"
TESLA_OAUTH_STATE_SESSION_KEY = "tesla_oauth_state"
partner_admin_service = TeslaPartnerAdminService(settings)
logger = logging.getLogger(__name__)


def _runtime_services() -> RuntimeServices:
    return RuntimeServices(
        demo_tesla_client=DemoTeslaClient(),
        owner_tesla_client=TeslaOwnerApiClient(),
        fleet_tesla_client=TeslaFleetApiClient(settings),
        storage=LocalFileStorage(settings.data_dir),
        emailer=DeliveryEmailService(settings.data_dir, settings),
    )


def _load_user(db: Session, user_id: int) -> User | None:
    return db.scalar(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.google_account),
            selectinload(User.tesla_accounts).selectinload(TeslaAccount.vehicles),
            selectinload(User.vehicles).selectinload(Vehicle.tesla_account),
            selectinload(User.email_settings),
        )
    )


def _get_current_user(request: Request, db: Session) -> User:
    user = _load_user(db, get_session_user_id(request))
    if user is None:
        clear_session_user(request)
        raise HTTPException(status_code=401, detail="Deine Sitzung ist abgelaufen. Bitte erneut einloggen.")
    return user


def _active_sync_account(user: User) -> TeslaAccount | None:
    live_account = select_live_account(list(user.tesla_accounts), getattr(user, "preferred_live_sync_mode", "auto"))
    if live_account is not None:
        return live_account
    if settings.demo_mode:
        return next((account for account in user.tesla_accounts if account.mode == "demo"), None)
    return None


def _active_sync_mode(user: User) -> str:
    account = _active_sync_account(user)
    return account.mode if account is not None else "none"


def _is_admin(user: User) -> bool:
    return user_is_admin(settings, user.email)


def _require_admin_user(request: Request, db: Session) -> User:
    user = _get_current_user(request, db)
    if not _is_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Dieses Admin-Menue ist nur fuer Betreiber freigeschaltet. Bitte `ADMIN_EMAILS` pruefen.",
        )
    return user


def _extract_tesla_profile_email(profile_payload: dict[str, object]) -> str:
    response_payload = profile_payload.get("response")
    if isinstance(response_payload, dict):
        return str(response_payload.get("email") or "").strip().lower()
    return str(profile_payload.get("email") or "").strip().lower()


def _extract_region_base_url(region_payload: dict[str, object]) -> str | None:
    candidate_objects: list[object] = [region_payload, region_payload.get("response")]
    for candidate in candidate_objects:
        if not isinstance(candidate, dict):
            continue
        for key in ("fleet_api_base_url", "fleetApiBaseUrl", "base_url", "baseUrl", "api_base_url"):
            value = str(candidate.get(key) or "").strip()
            if value:
                return value.rstrip("/")
    return None


def _selected_accounting_targets(email_settings: EmailSetting | None) -> set[str]:
    if email_settings is None or not email_settings.accounting_targets_csv:
        return set()
    return {item.strip() for item in email_settings.accounting_targets_csv.split(",") if item.strip()}


def _google_error_redirect(user_is_authenticated: bool, message: str) -> RedirectResponse:
    target = "/dashboard" if user_is_authenticated else "/auth"
    return RedirectResponse(f"{target}?google_error={parse.quote(message)}", status_code=303)


def _serialize_current_user(db: Session, user: User) -> CurrentUserResponse:
    account = _active_sync_account(user)
    google_account = user.google_account
    preferred_live_sync_mode = normalize_preferred_live_sync_mode(getattr(user, "preferred_live_sync_mode", "auto"))
    live_account = select_live_account(list(user.tesla_accounts), preferred_live_sync_mode)
    live_modes = connected_live_modes(list(user.tesla_accounts))
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
    delivery_mode = "gmail" if google_gmail_send_available(google_account) else "smtp" if settings.smtp_host else "outbox"

    return CurrentUserResponse(
        email=user.email,
        vehicle_count=len(user.vehicles),
        invoice_count=invoice_count,
        email_recipients=recipients,
        last_synced_at=account.last_synced_at if account else None,
        delivery_mode=delivery_mode,
        smtp_configured=bool(settings.smtp_host),
        subject_template=(
            user.email_settings.subject_template if user.email_settings else "Neue Tesla-Rechnungen fuer {email}"
        ),
        attach_pdf=user.email_settings.attach_pdf if user.email_settings else True,
        employee_sender_email=user.email_settings.employee_sender_email if user.email_settings else None,
        accounting_targets=accounting_targets,
        available_accounting_targets=AVAILABLE_ACCOUNTING_TARGETS,
        implemented_accounting_targets=sorted(IMPLEMENTED_ACCOUNTING_TARGETS),
        vehicles=[
            VehicleResponse(
                id=vehicle.id,
                vin=vehicle.vin,
                nickname=vehicle.nickname,
                model=vehicle.model,
                account_mode=vehicle.tesla_account.mode if vehicle.tesla_account else "demo",
            )
            for vehicle in sorted(user.vehicles, key=lambda item: item.id)
        ],
        active_sync_mode=_active_sync_mode(user),
        demo_mode_enabled=settings.demo_mode,
        tesla_connected=live_account is not None and bool(live_account.refresh_token or live_account.access_token),
        tesla_account_email=live_account.tesla_account_email if live_account else None,
        tesla_last_error=live_account.last_error if live_account else None,
        tesla_connection_mode=live_account.mode if live_account else "none",
        preferred_live_sync_mode=preferred_live_sync_mode,
        connected_tesla_modes=live_modes,
        google_connected=google_account is not None,
        google_email=google_account.google_email if google_account else None,
        google_gmail_send_enabled=google_gmail_send_available(google_account),
        google_oauth_available=google_oauth_available(settings),
        google_oauth_start_path="/api/v1/auth/google/start" if google_oauth_available(settings) else None,
        tesla_oauth_available=tesla_oauth_available(settings),
        tesla_oauth_start_path="/api/v1/tesla/oauth/start" if tesla_oauth_available(settings) else None,
        tesla_owner_import_available=settings.enable_tesla_owner_import,
        is_admin=_is_admin(user),
        admin_path="/admin" if _is_admin(user) else None,
    )


def _coerce_invoice_amount(invoice: Invoice) -> float:
    try:
        return float(invoice.amount or 0)
    except Exception:
        logger.warning("Stored invoice amount could not be converted to float. invoice_id=%s", invoice.invoice_id)
        return 0.0


def _repair_invoices_from_stored_pdfs(db: Session, invoices: list[Invoice]) -> int:
    """Backfill missing amounts from already downloaded PDFs so existing live history becomes readable."""

    repaired_count = 0
    for invoice in invoices:
        current_amount = _coerce_invoice_amount(invoice)
        if current_amount > 0 and invoice.currency:
            continue

        parsed_amount, parsed_currency = extract_amount_and_currency_from_pdf_path(invoice.pdf_path)
        updated = False
        if parsed_amount is not None and parsed_amount > 0 and current_amount <= 0:
            invoice.amount = float(parsed_amount)
            updated = True
        normalized_currency = (parsed_currency or "").strip().upper()
        if normalized_currency and (not invoice.currency or invoice.currency.strip().upper() != normalized_currency):
            invoice.currency = normalized_currency
            updated = True
        if updated:
            repaired_count += 1

    if repaired_count:
        db.commit()

    return repaired_count


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


@router.get("/auth/google/start", summary="Redirect the browser into Google OAuth for login and optional Gmail sending")
def start_google_oauth(request: Request, db: Session = Depends(get_db_session)) -> RedirectResponse:
    current_user_id = request.session.get("user_id")
    user = _load_user(db, current_user_id) if isinstance(current_user_id, int) else None

    try:
        authorization_request = build_google_authorization_request(settings)
    except GoogleAuthenticationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    request.session[GOOGLE_OAUTH_STATE_SESSION_KEY] = authorization_request.state
    if user is not None:
        request.session[GOOGLE_OAUTH_LINK_USER_ID_SESSION_KEY] = user.id
    else:
        request.session.pop(GOOGLE_OAUTH_LINK_USER_ID_SESSION_KEY, None)
    return RedirectResponse(authorization_request.url, status_code=303)


@router.get("/auth/google/callback", summary="Handle Google OAuth for login and Gmail sending")
def google_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db_session),
) -> RedirectResponse:
    current_user_id = request.session.get("user_id")
    link_user_id = request.session.get(GOOGLE_OAUTH_LINK_USER_ID_SESSION_KEY)
    expected_state = request.session.get(GOOGLE_OAUTH_STATE_SESSION_KEY)
    request.session.pop(GOOGLE_OAUTH_STATE_SESSION_KEY, None)
    request.session.pop(GOOGLE_OAUTH_LINK_USER_ID_SESSION_KEY, None)

    initiating_user = None
    for candidate_user_id in (link_user_id, current_user_id):
        if isinstance(candidate_user_id, int):
            initiating_user = _load_user(db, candidate_user_id)
            if initiating_user is not None:
                break

    if error:
        return _google_error_redirect(initiating_user is not None, error_description or error)
    if not code:
        return _google_error_redirect(
            initiating_user is not None,
            "Google hat keinen OAuth-Code zurueckgegeben. Bitte den Login erneut starten.",
        )
    if not state or state != expected_state:
        return _google_error_redirect(
            initiating_user is not None,
            "Die Google-OAuth-Antwort enthaelt einen ungueltigen State. Bitte den Login erneut starten.",
        )

    google_client = GoogleOAuthClient(settings)
    try:
        token_bundle = google_client.exchange_authorization_code(code)
        profile = google_client.fetch_user_profile(token_bundle.access_token)
    except (GoogleAuthenticationError, GoogleApiError) as exc:
        return _google_error_redirect(initiating_user is not None, str(exc))

    if initiating_user is not None and initiating_user.email != profile.email:
        return _google_error_redirect(
            True,
            "Das aktuell eingeloggte Konto nutzt eine andere E-Mail-Adresse als dein Google-Konto. "
            "Bitte melde dich entweder mit derselben Adresse an oder logge dich vorher aus.",
        )

    google_account_owner = db.scalar(select(GoogleAccount).where(GoogleAccount.google_subject == profile.subject))
    if google_account_owner is not None and initiating_user is not None and google_account_owner.user_id != initiating_user.id:
        return _google_error_redirect(
            True,
            "Dieses Google-Konto ist bereits mit einem anderen TeslaInvoiceAutomatic-Konto verbunden.",
        )

    if google_account_owner is not None and initiating_user is None:
        target_user = google_account_owner.user
    elif initiating_user is not None:
        target_user = initiating_user
    else:
        target_user = db.scalar(select(User).where(User.email == profile.email))
        if target_user is None:
            target_user = User(email=profile.email, password_hash=None, subscription_plan="basic")
            db.add(target_user)
            db.flush()

    if target_user is None:
        return _google_error_redirect(False, "Google-Konto konnte keinem lokalen Benutzer zugeordnet werden.")

    google_account = target_user.google_account
    if google_account is None:
        google_account = GoogleAccount(user_id=target_user.id, google_subject=profile.subject, google_email=profile.email)
    elif google_account.google_subject != profile.subject:
        google_account.google_subject = profile.subject

    google_account.google_email = profile.email
    google_account.access_token = encrypt_secret(token_bundle.access_token)
    previous_refresh_token = google_account.refresh_token
    google_account.refresh_token = encrypt_secret(token_bundle.refresh_token) or previous_refresh_token
    google_account.expires_at = token_bundle.expires_at
    google_account.oauth_scope = token_bundle.scope or settings.google_oauth_scope
    google_account.picture_url = profile.picture_url
    google_account.last_error = None

    email_settings = ensure_email_settings(db, target_user, default_recipient=target_user.email)
    if not email_settings.recipients_csv:
        email_settings.recipients_csv = target_user.email

    db.add(target_user)
    db.add(email_settings)
    db.add(google_account)
    db.commit()
    db.refresh(target_user)

    set_session_user(request, target_user.id)
    return RedirectResponse("/dashboard?google=connected", status_code=303)


@router.get("/me", response_model=CurrentUserResponse, summary="Return dashboard data for the logged-in user")
def me(request: Request, db: Session = Depends(get_db_session)) -> CurrentUserResponse:
    user = _get_current_user(request, db)
    return _serialize_current_user(db, user)


@router.get("/admin/fleet/status", response_model=FleetAdminStatusResponse, summary="Return Tesla Fleet partner setup status for operators")
def fleet_admin_status(request: Request, db: Session = Depends(get_db_session)) -> FleetAdminStatusResponse:
    _require_admin_user(request, db)
    status = partner_admin_service.current_status()
    return FleetAdminStatusResponse(
        app_base_url=status.app_base_url,
        app_domain=status.app_domain,
        callback_url=status.callback_url,
        fleet_api_base_url=status.fleet_api_base_url,
        sync_interval_seconds=settings.sync_interval_seconds,
        oauth_ready=status.oauth_ready,
        register_ready=status.register_ready,
        public_key_url=status.public_key_url,
        public_key_present=status.public_key_present,
        private_key_present=status.private_key_present,
        public_key_pem=status.public_key_pem,
        public_key_fingerprint=status.public_key_fingerprint,
        key_generated_at=status.key_generated_at,
        partner_token_scope=status.partner_token_scope,
        last_register_status=status.last_register_status,
        last_register_message=status.last_register_message,
        last_register_http_status=status.last_register_http_status,
        last_register_attempt_at=status.last_register_attempt_at,
        last_register_success_at=status.last_register_success_at,
        last_verify_status=status.last_verify_status,
        last_verify_message=status.last_verify_message,
        last_verify_http_status=status.last_verify_http_status,
        last_verify_at=status.last_verify_at,
    )


@router.get("/admin/users", response_model=list[AdminRegisteredUserResponse], summary="List registered beta users with their vehicles")
def admin_users(request: Request, db: Session = Depends(get_db_session)) -> list[AdminRegisteredUserResponse]:
    _require_admin_user(request, db)
    users = db.scalars(
        select(User)
        .options(
            selectinload(User.tesla_accounts).selectinload(TeslaAccount.vehicles),
            selectinload(User.vehicles).selectinload(Vehicle.tesla_account),
        )
        .order_by(User.created_at.desc(), User.id.desc())
    ).all()
    serialized_users: list[AdminRegisteredUserResponse] = []
    for user in users:
        active_account = _active_sync_account(user)
        serialized_users.append(
            AdminRegisteredUserResponse(
                id=user.id,
                email=user.email,
                created_at=user.created_at,
                active_sync_mode=_active_sync_mode(user),
                tesla_connection_mode=active_account.mode if active_account else "none",
                last_synced_at=active_account.last_synced_at if active_account else None,
                vehicles=[
                    VehicleResponse(
                        id=vehicle.id,
                        vin=vehicle.vin,
                        nickname=vehicle.nickname,
                        model=vehicle.model,
                        account_mode=vehicle.tesla_account.mode if vehicle.tesla_account else "demo",
                    )
                    for vehicle in sorted(user.vehicles, key=lambda item: item.id)
                ],
            )
        )
    return serialized_users


@router.post("/admin/demo/purge", response_model=AdminActionResponse, summary="Delete all stored demo invoices and their PDFs")
def purge_demo_invoices(request: Request, db: Session = Depends(get_db_session)) -> AdminActionResponse:
    _require_admin_user(request, db)
    demo_invoices = db.scalars(select(Invoice).where(Invoice.source == "demo")).all()
    if not demo_invoices:
        return AdminActionResponse(
            status="noop",
            message="Es wurden keine Demo-Rechnungen gefunden. Das Archiv enthaelt bereits nur Live-Daten.",
            http_status=200,
        )

    deleted_invoice_count = len(demo_invoices)
    pdf_paths = {invoice.pdf_path for invoice in demo_invoices if invoice.pdf_path}
    for invoice in demo_invoices:
        db.delete(invoice)
    db.commit()

    deleted_file_count = 0
    for pdf_path in sorted(pdf_paths):
        try:
            Path(pdf_path).unlink(missing_ok=True)
            deleted_file_count += 1
        except OSError:
            logger.exception("Demo invoice PDF could not be deleted during cleanup. path=%s", pdf_path)

    return AdminActionResponse(
        status="success",
        message=(
            f"{deleted_invoice_count} Demo-Rechnungen wurden aus dem Archiv entfernt. "
            f"{deleted_file_count} PDF-Datei(en) wurden im Datenverzeichnis geloescht."
        ),
        http_status=200,
    )


@router.post("/admin/fleet/keys/generate", response_model=AdminActionResponse, summary="Generate or rotate the Tesla Fleet partner key pair")
def generate_fleet_keys(
    payload: FleetKeyGenerationRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> AdminActionResponse:
    _require_admin_user(request, db)
    try:
        result = partner_admin_service.generate_key_pair(force=payload.force)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AdminActionResponse(status=result.status, message=result.message, http_status=result.http_status)


@router.post("/admin/fleet/register", response_model=AdminActionResponse, summary="Register the Tesla partner app for the configured region")
def register_fleet_partner(request: Request, db: Session = Depends(get_db_session)) -> AdminActionResponse:
    _require_admin_user(request, db)
    try:
        result = partner_admin_service.register_partner_account()
    except (ValueError, TeslaAuthenticationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TeslaApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AdminActionResponse(status=result.status, message=result.message, http_status=result.http_status)


@router.post("/admin/fleet/verify", response_model=AdminActionResponse, summary="Verify whether Tesla already knows the hosted public key")
def verify_fleet_partner(request: Request, db: Session = Depends(get_db_session)) -> AdminActionResponse:
    _require_admin_user(request, db)
    try:
        result = partner_admin_service.verify_partner_registration()
    except (ValueError, TeslaAuthenticationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TeslaApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AdminActionResponse(status=result.status, message=result.message, http_status=result.http_status)


@router.get("/tesla/oauth/start", summary="Redirect the logged-in user into Tesla OAuth")
def start_tesla_oauth(request: Request, db: Session = Depends(get_db_session)) -> RedirectResponse:
    _get_current_user(request, db)

    try:
        authorization_request = build_tesla_authorization_request(settings)
    except TeslaAuthenticationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    request.session[TESLA_OAUTH_STATE_SESSION_KEY] = authorization_request.state
    return RedirectResponse(authorization_request.url, status_code=303)


@router.get("/tesla/oauth/callback", summary="Handle the Tesla OAuth callback and store the tokens")
def tesla_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db_session),
) -> RedirectResponse:
    user = _get_current_user(request, db)

    if error:
        return RedirectResponse(
            f"/dashboard?tesla_error={parse.quote(error_description or error)}",
            status_code=303,
        )
    if not code:
        return RedirectResponse("/dashboard?tesla_error=Tesla%20hat%20keinen%20Code%20zurueckgegeben.", status_code=303)

    expected_state = request.session.get(TESLA_OAUTH_STATE_SESSION_KEY)
    request.session.pop(TESLA_OAUTH_STATE_SESSION_KEY, None)
    if not state or state != expected_state:
        return RedirectResponse(
            "/dashboard?tesla_error=Die%20Tesla-OAuth-Antwort%20enthaelt%20einen%20ungueltigen%20State.",
            status_code=303,
        )

    fleet_client = TeslaFleetApiClient(settings)
    try:
        token_bundle = fleet_client.exchange_authorization_code(code)
        profile_payload = fleet_client.fetch_user_profile(token_bundle.access_token, token_bundle.fleet_api_base_url)
    except (TeslaAuthenticationError, TeslaApiError) as exc:
        return RedirectResponse(f"/dashboard?tesla_error={parse.quote(str(exc))}", status_code=303)

    profile_email = _extract_tesla_profile_email(profile_payload)
    try:
        region_payload = fleet_client.fetch_region(token_bundle.access_token, token_bundle.fleet_api_base_url)
        region_base_url = _extract_region_base_url(region_payload) or token_bundle.fleet_api_base_url
    except (TeslaAuthenticationError, TeslaApiError):
        region_base_url = token_bundle.fleet_api_base_url

    account = get_tesla_account_by_mode(db, user, "fleet_oauth")
    if account is None:
        email_seed = profile_email or user.email
        email_slug = hashlib.sha1(email_seed.encode("utf-8")).hexdigest()[:12]
        account = TeslaAccount(
            user_id=user.id,
            tesla_account_id=f"fleet-account-{email_slug}",
            mode="fleet_oauth",
        )

    account.tesla_account_email = profile_email or user.email
    account.access_token = encrypt_secret(token_bundle.access_token)
    account.refresh_token = encrypt_secret(token_bundle.refresh_token)
    account.expires_at = token_bundle.expires_at
    account.auth_base_url = "https://auth.tesla.com"
    account.fleet_api_base_url = region_base_url
    account.oauth_scope = token_bundle.scope or settings.tesla_oauth_scope
    account.last_error = None
    db.add(account)
    db.flush()

    try:
        fleet_vehicles = fleet_client.fetch_vehicles(account)
        imported_count = 0
        for fleet_vehicle in fleet_vehicles:
            upsert_vehicle_for_account(
                db,
                user,
                account,
                fleet_vehicle.vin,
                fleet_vehicle.display_name,
                model=fleet_vehicle.model,
                tesla_vehicle_id=fleet_vehicle.tesla_vehicle_id,
            )
            imported_count += 1
    except (TeslaAuthenticationError, TeslaApiError, ValueError) as exc:
        account.last_error = str(exc)
        db.add(account)
        db.commit()
        return RedirectResponse(f"/dashboard?tesla_error={parse.quote(str(exc))}", status_code=303)

    db.add(account)
    db.commit()
    return RedirectResponse(
        f"/dashboard?tesla=connected&tesla_imported_vehicles={imported_count}",
        status_code=303,
    )


@router.post("/tesla/connect", summary="Store Tesla owner tokens for live invoice sync")
def connect_tesla(
    payload: TeslaConnectRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, object]:
    user = _get_current_user(request, db)

    if not settings.enable_tesla_owner_import:
        raise HTTPException(
            status_code=403,
            detail=(
                "Der inoffizielle Tesla-Token-Import ist fuer diese Installation deaktiviert. "
                "Bitte den Betreiber um `ENABLE_TESLA_OWNER_IMPORT=true` oder nutze den Fleet-Login."
            ),
        )

    try:
        imported_tokens = build_imported_tokens(
            tesla_account_email=payload.tesla_account_email,
            cache_json=payload.cache_json,
            access_token=payload.access_token,
            refresh_token=payload.refresh_token,
            auth_base_url=payload.auth_base_url,
        )
    except TeslaTokenImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    account = get_tesla_account_by_mode(db, user, "owner_api")
    if account is None:
        email_slug = hashlib.sha1(imported_tokens.tesla_account_email.encode("utf-8")).hexdigest()[:12]
        account = TeslaAccount(
            user_id=user.id,
            tesla_account_id=f"owner-account-{email_slug}",
            mode="owner_api",
        )

    account.tesla_account_email = imported_tokens.tesla_account_email
    account.access_token = encrypt_secret(imported_tokens.access_token)
    account.refresh_token = encrypt_secret(imported_tokens.refresh_token)
    account.expires_at = imported_tokens.expires_at
    account.auth_base_url = imported_tokens.auth_base_url
    account.ownership_base_url = payload.ownership_base_url or DEFAULT_OWNERSHIP_BASE_URL
    account.device_language = payload.device_language or DEFAULT_DEVICE_LANGUAGE
    account.device_country = payload.device_country or DEFAULT_DEVICE_COUNTRY
    account.http_locale = payload.http_locale or DEFAULT_HTTP_LOCALE
    account.last_error = None
    db.add(account)
    db.flush()

    try:
        TeslaOwnerApiClient().ensure_valid_access_token(account)
    except TeslaAuthenticationError as exc:
        account.last_error = str(exc)
        db.add(account)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TeslaApiError as exc:
        account.last_error = str(exc)
        db.add(account)
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    db.add(account)
    db.commit()
    db.refresh(account)
    return {
        "message": (
            "Inoffizieller Tesla-Zugang wurde gespeichert. Fuehre jetzt einen Live-Sync fuer deine VINs aus, "
            "um echte Rechnungen ohne Fleet-Login zu laden."
        ),
        "tesla_account_email": account.tesla_account_email,
        "mode": account.mode,
    }


@router.post("/settings/tesla-mode", summary="Store the preferred Tesla live mode for VIN linking and syncs")
def save_tesla_mode_preference(
    payload: TeslaModePreferenceRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, str]:
    user = _get_current_user(request, db)
    user.preferred_live_sync_mode = payload.preferred_live_sync_mode
    db.add(user)
    db.commit()
    return {
        "message": "Der bevorzugte Tesla-Live-Weg wurde gespeichert.",
        "preferred_live_sync_mode": user.preferred_live_sync_mode,
    }


@router.post("/vehicles", response_model=VehicleResponse, summary="Add a VIN to the current account")
def add_vehicle(
    payload: VehicleCreateRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> VehicleResponse:
    user = _get_current_user(request, db)
    try:
        account = get_preferred_user_account(db, user, allow_demo=settings.demo_mode)
        vehicle = upsert_vehicle_for_account(db, user, account, payload.vin, payload.nickname, model="Tesla")
    except (ValueError, TeslaAuthenticationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(vehicle)
    return VehicleResponse(
        id=vehicle.id,
        vin=vehicle.vin,
        nickname=vehicle.nickname,
        model=vehicle.model,
        account_mode=vehicle.tesla_account.mode,
    )


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
    email_settings.employee_sender_email = payload.employee_sender_email
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
    copy_recipients = (
        [payload.recipient_override]
        if payload.recipient_override
        else [item.strip() for item in (user.email_settings.recipients_csv if user.email_settings else "").split(",") if item.strip()]
    )
    if not copy_recipients and "Circula" not in _selected_accounting_targets(user.email_settings):
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
    selected_targets = _selected_accounting_targets(user.email_settings)
    target_recipients = copy_recipients
    cc_recipients: list[str] = []
    from_email: str | None = None
    message = (
        "Dies ist eine Testrechnung aus dem TeslaInvoiceAutomatic SaaS MVP. "
        "Wenn diese Nachricht ankommt, funktioniert dein aktueller SMTP-Pfad."
    )
    if "Circula" in selected_targets:
        if not user.email_settings or not user.email_settings.employee_sender_email:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Circula ist aktiv, aber es fehlt die sichtbare Absenderadresse. "
                    "Bitte zuerst in den Versand-Einstellungen `Sichtbarer Absender fuer Circula (Von-Adresse)` setzen."
                ),
            )
        target_recipients = ["receipts@in.circula.com"]
        cc_recipients = copy_recipients
        from_email = user.email_settings.employee_sender_email
        message = (
            "Dies ist eine Circula-Testrechnung aus dem TeslaInvoiceAutomatic SaaS MVP. "
            "Circula ist Hauptempfaenger, gespeicherte Empfaenger laufen als CC mit. "
            "Die angegebene Mitarbeiter-Adresse wird als sichtbarer Von-Absender gesetzt."
        )

    delivery_mode = DeliveryEmailService(settings.data_dir, settings).send_message(
        recipients=target_recipients,
        subject=f"Testrechnung fuer {user.email}",
        body=message,
        attachment_paths=[pdf_path],
        from_email=from_email,
        cc_recipients=cc_recipients,
        google_account=user.google_account,
    )

    return {
        "message": "Testmail wurde verarbeitet.",
        "delivery_mode": delivery_mode,
        "recipients": target_recipients,
        "cc_recipients": cc_recipients,
        "from_email": from_email or settings.default_from_email,
    }


@router.post("/sync/run", summary="Generate and send new demo invoices for the logged-in user")
def run_sync(
    payload: ManualSyncRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> dict[str, object]:
    user = _get_current_user(request, db)

    sync_service = InvoiceSyncService(db, _runtime_services())
    try:
        summary = sync_service.sync_user(user, manual_demo_invoice=payload.include_fresh_demo_invoice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TeslaAuthenticationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (TeslaApiError, InvoiceDownloadError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "message": "Sync wurde erfolgreich ausgefuehrt.",
        "created_count": summary.created_count,
        "skipped_count": summary.skipped_count,
        "emailed_recipients": summary.emailed_recipients,
        "delivery_mode": summary.delivery_mode,
        "sync_mode": summary.sync_mode,
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
    _repair_invoices_from_stored_pdfs(db, invoices)
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
