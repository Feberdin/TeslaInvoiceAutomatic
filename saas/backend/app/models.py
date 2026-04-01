"""
Purpose: Define relational tables for users, Tesla accounts, vehicles, invoices and email settings.
Input/Output: SQLAlchemy maps these models to PostgreSQL or SQLite tables.
Invariants: User emails and invoice IDs stay unique, invoices always belong to both a user and a vehicle, and Tesla accounts keep enough metadata to refresh real owner tokens safely.
Debug: If persisted data looks inconsistent, start by checking the relationships, account mode fields and unique constraints in this file.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(Text(), nullable=True)
    subscription_plan: Mapped[str] = mapped_column(String(50), default="basic")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    tesla_accounts: Mapped[list["TeslaAccount"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    email_settings: Mapped["EmailSetting | None"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")


class TeslaAccount(Base):
    __tablename__ = "tesla_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tesla_account_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(50), default="demo")
    tesla_account_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text(), nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text(), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auth_base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fleet_api_base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ownership_base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    device_country: Mapped[str | None] = mapped_column(String(16), nullable=True)
    http_locale: Mapped[str | None] = mapped_column(String(32), nullable=True)
    oauth_scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="tesla_accounts")
    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="tesla_account", cascade="all, delete-orphan")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tesla_account_id: Mapped[int] = mapped_column(ForeignKey("tesla_accounts.id"), index=True)
    tesla_vehicle_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    vin: Mapped[str] = mapped_column(String(32), unique=True)
    model: Mapped[str] = mapped_column(String(100))
    nickname: Mapped[str] = mapped_column(String(100))

    user: Mapped["User"] = relationship(back_populates="vehicles")
    tesla_account: Mapped["TeslaAccount"] = relationship(back_populates="vehicles")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="vehicle", cascade="all, delete-orphan")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    charge_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    location: Mapped[str] = mapped_column(String(255), default="Tesla Supercharger")
    pdf_path: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(50), default="demo")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped["User"] = relationship(back_populates="invoices")
    vehicle: Mapped["Vehicle"] = relationship(back_populates="invoices")


class EmailSetting(Base):
    __tablename__ = "email_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    recipients_csv: Mapped[str] = mapped_column(Text(), default="")
    subject_template: Mapped[str] = mapped_column(String(255), default="Neue Tesla-Rechnungen für {email}")
    accounting_targets_csv: Mapped[str] = mapped_column(Text(), default="")
    attach_pdf: Mapped[bool] = mapped_column(Boolean(), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    user: Mapped["User"] = relationship(back_populates="email_settings")
