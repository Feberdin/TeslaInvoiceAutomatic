"""
Purpose: Validate incoming API payloads and shape outgoing API responses.
Input/Output: FastAPI uses these models to parse requests and serialize responses safely.
Invariants: User-facing data is normalized early, especially e-mail addresses and recipient lists.
Debug: If an API request fails with validation errors, inspect the field validators in this module first.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.utils import validate_email_address, validate_recipient_list


class UserCreateRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return validate_email_address(value)


class DemoTeslaConnectRequest(BaseModel):
    user_email: str
    vehicle_count: int = Field(default=1, ge=1, le=3)

    @field_validator("user_email")
    @classmethod
    def validate_user_email(cls, value: str) -> str:
        return validate_email_address(value)


class EmailSettingsRequest(BaseModel):
    user_email: str
    recipients: list[str]
    subject_template: str = Field(default="Neue Tesla-Rechnungen für {email}", min_length=5, max_length=255)
    attach_pdf: bool = True

    @field_validator("user_email")
    @classmethod
    def validate_user_email(cls, value: str) -> str:
        return validate_email_address(value)

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, value: list[str]) -> list[str]:
        return validate_recipient_list(value)


class ManualSyncRequest(BaseModel):
    user_email: str

    @field_validator("user_email")
    @classmethod
    def validate_user_email(cls, value: str) -> str:
        return validate_email_address(value)


class InvoiceResponse(BaseModel):
    invoice_id: str
    amount: float
    currency: str
    location: str
    charge_started_at: datetime
    vehicle_name: str
    pdf_download_url: str


class StatusResponse(BaseModel):
    user_exists: bool
    tesla_connected: bool
    vehicle_count: int
    invoice_count: int
    email_recipients: list[str]
    last_synced_at: datetime | None

