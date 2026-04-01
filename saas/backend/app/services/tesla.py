"""
Purpose: Provide the Tesla integration boundary and a demo implementation for local testing.
Input/Output: Creates demo accounts and vehicles, returns charging sessions, and generates invoice PDFs.
Invariants: Demo IDs stay deterministic per user, while manual sync can add one fresh invoice for visible testing.
Debug: If no invoices are created, inspect the sessions returned by `list_recent_sessions`.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import ChargingSession
from app.models import TeslaAccount, User, Vehicle
from app.pdf_utils import generate_demo_invoice_pdf
from app.utils import normalize_email, validate_vin


class DemoTeslaClient:
    def ensure_demo_account(self, db: Session, user: User) -> TeslaAccount:
        email_slug = hashlib.sha1(normalize_email(user.email).encode("utf-8")).hexdigest()[:10]
        tesla_account_id = f"demo-account-{email_slug}"
        account = db.scalar(select(TeslaAccount).where(TeslaAccount.user_id == user.id))

        if account is None:
            account = TeslaAccount(user_id=user.id, tesla_account_id=tesla_account_id, mode="demo")
            db.add(account)
            db.flush()

        return account

    def upsert_vehicle(self, db: Session, user: User, vin: str, nickname: str = "") -> Vehicle:
        normalized_vin = validate_vin(vin)
        existing_vehicle = db.scalar(select(Vehicle).where(Vehicle.vin == normalized_vin))
        if existing_vehicle and existing_vehicle.user_id != user.id:
            raise ValueError(
                f"Die VIN {normalized_vin} ist bereits einem anderen Nutzer zugeordnet. Bitte pruefe die Eingabe."
            )

        account = self.ensure_demo_account(db, user)
        if existing_vehicle is None:
            existing_vehicle = Vehicle(
                user=user,
                tesla_account=account,
                tesla_vehicle_id=f"manual-{normalized_vin.lower()}",
                vin=normalized_vin,
                model="Tesla",
                nickname=nickname.strip() or f"Tesla {normalized_vin[-4:]}",
            )
            db.add(existing_vehicle)
        else:
            existing_vehicle.tesla_account = account
            existing_vehicle.nickname = nickname.strip() or existing_vehicle.nickname or f"Tesla {normalized_vin[-4:]}"

        db.flush()
        return existing_vehicle

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
