"""
Purpose: Validate incoming API payloads and shape outgoing API responses.
Input/Output: FastAPI uses these models to parse requests and serialize responses safely.
Invariants: User-facing data is normalized early, especially e-mail addresses and recipient lists.
Debug: If an API request fails with validation errors, inspect the field validators in this module first.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.auth import validate_password_strength
from app.utils import validate_email_address, validate_recipient_list, validate_vin


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return validate_email_address(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_strength(value)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_login_email(cls, value: str) -> str:
        return validate_email_address(value)


class EmailSettingsRequest(BaseModel):
    recipients: list[str]
    subject_template: str = Field(default="Neue Tesla-Rechnungen für {email}", min_length=5, max_length=255)
    attach_pdf: bool = True
    accounting_targets: list[str] = Field(default_factory=list)
    employee_sender_email: str | None = None

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, value: list[str]) -> list[str]:
        return validate_recipient_list(value)

    @field_validator("employee_sender_email")
    @classmethod
    def validate_optional_employee_sender_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return validate_email_address(value)


class VehicleCreateRequest(BaseModel):
    vin: str = Field(..., min_length=17, max_length=17)
    nickname: str = Field(default="", max_length=100)

    @field_validator("vin")
    @classmethod
    def validate_vehicle_vin(cls, value: str) -> str:
        return validate_vin(value)


class TeslaConnectRequest(BaseModel):
    tesla_account_email: str = Field(..., min_length=3, max_length=255)
    cache_json: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    auth_base_url: str = Field(default="https://auth.tesla.com", min_length=8, max_length=255)
    ownership_base_url: str = Field(
        default="https://ownership.tesla.com/mobile-app/charging",
        min_length=8,
        max_length=255,
    )
    device_language: str = Field(default="de", min_length=2, max_length=16)
    device_country: str = Field(default="DE", min_length=2, max_length=16)
    http_locale: str = Field(default="de_DE", min_length=2, max_length=32)

    @field_validator("tesla_account_email")
    @classmethod
    def validate_tesla_account_email(cls, value: str) -> str:
        return validate_email_address(value)

    @field_validator("cache_json", "access_token", "refresh_token")
    @classmethod
    def normalize_optional_secret_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("auth_base_url", "ownership_base_url")
    @classmethod
    def validate_url_like_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("https://"):
            raise ValueError("Tesla-URLs muessen mit https:// beginnen.")
        return normalized.rstrip("/")

    @field_validator("device_language", "device_country", "http_locale")
    @classmethod
    def normalize_locale_fields(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_credentials_present(self) -> "TeslaConnectRequest":
        if self.cache_json or self.refresh_token or self.access_token:
            return self
        raise ValueError(
            "Bitte entweder einen TeslaPy-/tesla_ha-Cache oder Tesla-Tokens einfuegen, bevor du verbindest."
        )


class TeslaModePreferenceRequest(BaseModel):
    preferred_live_sync_mode: str = Field(default="auto", min_length=4, max_length=32)

    @field_validator("preferred_live_sync_mode")
    @classmethod
    def validate_preferred_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "fleet_oauth", "owner_api"}:
            raise ValueError("Erlaubt sind nur `auto`, `fleet_oauth` oder `owner_api`.")
        return normalized


class FleetKeyGenerationRequest(BaseModel):
    force: bool = False


class ManualSyncRequest(BaseModel):
    include_fresh_demo_invoice: bool = True


class TestEmailRequest(BaseModel):
    recipient_override: str | None = None

    @field_validator("recipient_override")
    @classmethod
    def validate_optional_recipient(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        return validate_email_address(value)


class VehicleResponse(BaseModel):
    id: int
    vin: str
    nickname: str
    model: str
    account_mode: str


class InvoiceResponse(BaseModel):
    invoice_id: str
    amount: float
    currency: str
    location: str
    charge_started_at: datetime
    vehicle_name: str
    pdf_download_url: str
    source: str


class SessionResponse(BaseModel):
    authenticated: bool
    email: str | None = None


class CurrentUserResponse(BaseModel):
    email: str
    vehicle_count: int
    invoice_count: int
    email_recipients: list[str]
    last_synced_at: datetime | None
    delivery_mode: str
    smtp_configured: bool
    subject_template: str
    attach_pdf: bool
    employee_sender_email: str | None
    accounting_targets: list[str]
    available_accounting_targets: list[str]
    implemented_accounting_targets: list[str]
    vehicles: list[VehicleResponse]
    active_sync_mode: str
    demo_mode_enabled: bool
    tesla_connected: bool
    tesla_account_email: str | None
    tesla_last_error: str | None
    tesla_connection_mode: str
    preferred_live_sync_mode: str
    connected_tesla_modes: list[str]
    google_connected: bool
    google_email: str | None
    google_gmail_send_enabled: bool
    google_oauth_available: bool
    google_oauth_start_path: str | None
    tesla_oauth_available: bool
    tesla_oauth_start_path: str | None
    tesla_owner_import_available: bool
    is_admin: bool
    admin_path: str | None


class FleetAdminStatusResponse(BaseModel):
    app_base_url: str
    app_domain: str
    callback_url: str
    fleet_api_base_url: str
    sync_interval_seconds: int
    oauth_ready: bool
    register_ready: bool
    public_key_url: str
    public_key_present: bool
    private_key_present: bool
    public_key_pem: str | None
    public_key_fingerprint: str | None
    key_generated_at: str | None
    partner_token_scope: str
    last_register_status: str
    last_register_message: str | None
    last_register_http_status: int | None
    last_register_attempt_at: str | None
    last_register_success_at: str | None
    last_verify_status: str
    last_verify_message: str | None
    last_verify_http_status: int | None
    last_verify_at: str | None


class AdminActionResponse(BaseModel):
    status: str
    message: str
    http_status: int | None = None


class AdminRegisteredUserResponse(BaseModel):
    id: int
    email: str
    created_at: datetime
    active_sync_mode: str
    tesla_connection_mode: str
    last_synced_at: datetime | None
    vehicles: list[VehicleResponse]
