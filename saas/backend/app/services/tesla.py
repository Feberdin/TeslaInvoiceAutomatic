"""
Purpose: Provide reusable Tesla account and vehicle helpers plus the demo Tesla implementation.
Input/Output: Creates demo accounts, links VINs to the active Tesla account and returns demo charging sessions or PDFs.
Invariants: Demo IDs stay deterministic per user, VIN uniqueness is enforced across users and manual sync can add one fresh invoice for visible testing.
Debug: If a VIN ends up on the wrong Tesla mode, inspect `upsert_vehicle_for_account` and the selected account mode before looking at the UI.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import TeslaAuthenticationError
from app.domain import ChargingSession
from app.models import TeslaAccount, User, Vehicle
from app.pdf_utils import generate_demo_invoice_pdf
from app.utils import normalize_email, validate_vin


def get_tesla_account_by_mode(db: Session, user: User, mode: str) -> TeslaAccount | None:
    return db.scalar(select(TeslaAccount).where(TeslaAccount.user_id == user.id, TeslaAccount.mode == mode))


def get_preferred_user_account(db: Session, user: User, *, allow_demo: bool) -> TeslaAccount:
    fleet_account = get_tesla_account_by_mode(db, user, "fleet_oauth")
    if fleet_account is not None:
        return fleet_account
    owner_account = get_tesla_account_by_mode(db, user, "owner_api")
    if owner_account is not None:
        return owner_account
    if allow_demo:
        return DemoTeslaClient().ensure_demo_account(db, user)
    raise TeslaAuthenticationError(
        "Fuer dieses Konto ist noch keine echte Tesla-Verbindung gespeichert. "
        "Bitte zuerst im Dashboard Tesla-Zugangsdaten importieren."
    )


def upsert_vehicle_for_account(
    db: Session,
    user: User,
    account: TeslaAccount,
    vin: str,
    nickname: str = "",
    *,
    model: str = "Tesla",
    tesla_vehicle_id: str | None = None,
) -> Vehicle:
    """Create or relink one VIN for the chosen Tesla account.

    Example:
        - same user saved the VIN earlier in demo mode
        - later the user connects a real Tesla account
        - saving the VIN again relinks it from `demo` to `owner_api`
    """

    normalized_vin = validate_vin(vin)
    existing_vehicle = db.scalar(select(Vehicle).where(Vehicle.vin == normalized_vin))
    if existing_vehicle and existing_vehicle.user_id != user.id:
        raise ValueError(
            f"Die VIN {normalized_vin} ist bereits einem anderen Nutzer zugeordnet. Bitte pruefe die Eingabe."
        )

    resolved_vehicle_id = tesla_vehicle_id or f"{account.mode}-{normalized_vin.lower()}"
    resolved_nickname = nickname.strip() or (existing_vehicle.nickname if existing_vehicle else "") or f"Tesla {normalized_vin[-4:]}"
    resolved_model = model.strip() or (existing_vehicle.model if existing_vehicle else "") or "Tesla"

    if existing_vehicle is None:
        existing_vehicle = Vehicle(
            user=user,
            tesla_account=account,
            tesla_vehicle_id=resolved_vehicle_id,
            vin=normalized_vin,
            model=resolved_model,
            nickname=resolved_nickname,
        )
        db.add(existing_vehicle)
    else:
        existing_vehicle.user = user
        existing_vehicle.tesla_account = account
        existing_vehicle.tesla_vehicle_id = resolved_vehicle_id
        existing_vehicle.nickname = resolved_nickname
        existing_vehicle.model = resolved_model

    db.flush()
    return existing_vehicle


class DemoTeslaClient:
    def ensure_demo_account(self, db: Session, user: User) -> TeslaAccount:
        email_slug = hashlib.sha1(normalize_email(user.email).encode("utf-8")).hexdigest()[:10]
        tesla_account_id = f"demo-account-{email_slug}"
        account = get_tesla_account_by_mode(db, user, "demo")

        if account is None:
            account = TeslaAccount(
                user_id=user.id,
                tesla_account_id=tesla_account_id,
                mode="demo",
                tesla_account_email=user.email,
            )
            db.add(account)
            db.flush()

        return account

    def upsert_vehicle(self, db: Session, user: User, vin: str, nickname: str = "") -> Vehicle:
        account = self.ensure_demo_account(db, user)
        return upsert_vehicle_for_account(db, user, account, vin, nickname, model="Tesla")

    def provision_demo_account(self, db: Session, user: User, vehicle_count: int) -> tuple[TeslaAccount, list[Vehicle]]:
        account = self.ensure_demo_account(db, user)

        existing_vehicles = list(account.vehicles)
        existing_vehicle_ids = {vehicle.tesla_vehicle_id for vehicle in existing_vehicles}

        # Vehicles are only added, never deleted automatically, so invoices remain traceable.
        for index in range(1, vehicle_count + 1):
            tesla_vehicle_id = f"{account.tesla_account_id}-vehicle-{index}"
            if tesla_vehicle_id in existing_vehicle_ids:
                continue

            vin_suffix = hashlib.sha1(f"{tesla_vehicle_id}-vin".encode("utf-8")).hexdigest()[:10].upper()
            vehicle = Vehicle(
                user=user,
                tesla_account=account,
                tesla_vehicle_id=tesla_vehicle_id,
                vin=f"5YJSA7E{vin_suffix}",
                model="Model Y" if index % 2 else "Model 3",
                nickname=f"Demo Tesla {index}",
            )
            db.add(vehicle)

        db.flush()
        vehicles = db.scalars(select(Vehicle).where(Vehicle.tesla_account_id == account.id).order_by(Vehicle.id)).all()
        return account, vehicles

    def list_recent_sessions(
        self,
        account: TeslaAccount,
        vehicle: Vehicle,
        *,
        fresh_seed: str | None = None,
    ) -> list[ChargingSession]:
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        base_timestamps = [
            now - timedelta(days=2, hours=3),
            now - timedelta(days=1, hours=5),
            now - timedelta(hours=6),
        ]
        sessions: list[ChargingSession] = []

        # The amount formula is intentionally simple and deterministic so duplicates are easy to spot.
        for index, started_at in enumerate(base_timestamps, start=1):
            hour_bucket = started_at.strftime("%Y%m%d%H")
            sessions.append(
                ChargingSession(
                    invoice_id=f"{vehicle.tesla_vehicle_id}-{hour_bucket}-{index}",
                    started_at=started_at,
                    amount=Decimal("12.50") + Decimal(index * 3),
                    currency="EUR",
                    location=f"Tesla Supercharger Demo Standort {index}",
                )
            )

        if fresh_seed:
            sessions.append(
                ChargingSession(
                    invoice_id=f"{vehicle.tesla_vehicle_id}-manual-{fresh_seed}",
                    started_at=now,
                    amount=Decimal("28.90"),
                    currency="EUR",
                    location="Tesla Supercharger Live Demo",
                )
            )

        return sessions

    def download_invoice_pdf(self, invoice_id: str, vehicle: Vehicle, amount: Decimal, currency: str, location: str) -> bytes:
        lines = [
            "Tesla Invoice Automatic SaaS Demo",
            f"Invoice ID: {invoice_id}",
            f"Vehicle: {vehicle.nickname} ({vehicle.model})",
            f"VIN: {vehicle.vin}",
            f"Amount: {amount} {currency}",
            f"Location: {location}",
            "Hinweis: Dies ist eine Demo-Rechnung fuer den MVP-Testbetrieb.",
        ]
        return generate_demo_invoice_pdf(lines)
