"""
Purpose: Implement the official Tesla Fleet OAuth flow and the live charging endpoints used after customer login.
Input/Output: Builds Tesla authorize URLs, exchanges callback codes for tokens, refreshes tokens and turns Fleet charging history into invoice candidates and PDFs.
Invariants: Fleet OAuth uses Tesla's official `/authorize` and `/token` endpoints, refresh tokens are rotated and re-saved, and all live API calls use the configured Fleet API audience/base URL.
Debug: If customer login succeeds but sync fails, inspect the stored `fleet_api_base_url`, the callback error text and the exact Fleet API status code before changing any UI copy.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib import error, parse, request

from app.config import Settings
from app.domain import ChargingSession
from app.errors import InvoiceDownloadError, TeslaApiError, TeslaAuthenticationError
from app.token_store import decrypt_secret, encrypt_secret
from app.utils import normalize_email, validate_vin

if TYPE_CHECKING:
    from app.models import TeslaAccount


TESLA_AUTHORIZE_URL = "https://auth.tesla.com/oauth2/v3/authorize"
TESLA_TOKEN_URL = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"
DEFAULT_TIMEOUT_SECONDS = 30
TOKEN_REFRESH_SKEW_SECONDS = 300
DEFAULT_CURRENCY = "EUR"
AMOUNT_CANDIDATE_KEYS = (
    "amount",
    "invoice_amount",
    "invoiceAmount",
    "charge_amount",
    "chargeAmount",
    "total_amount",
    "totalAmount",
    "price",
    "cost",
)
VEHICLE_RESULT_KEYS = ("response", "results", "data", "vehicles")
CHARGING_RESULT_KEYS = ("response", "results", "data", "charging_history", "history")


@dataclass(frozen=True)
class OAuthAuthorizationRequest:
    url: str
    state: str
    nonce: str


@dataclass(frozen=True)
class FleetTokenBundle:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    fleet_api_base_url: str
    token_type: str
    scope: str | None


@dataclass(frozen=True)
class FleetVehicleInfo:
    vin: str
    display_name: str
    model: str
    tesla_vehicle_id: str


@dataclass(frozen=True)
class _HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def tesla_oauth_available(settings: Settings) -> bool:
    return bool(
        settings.enable_tesla_fleet_oauth
        and settings.tesla_client_id
        and settings.tesla_client_secret
        and settings.app_base_url
    )


def build_tesla_authorization_request(settings: Settings) -> OAuthAuthorizationRequest:
    if not tesla_oauth_available(settings):
        raise TeslaAuthenticationError(
            "Tesla OAuth ist noch nicht fuer diese Installation konfiguriert. "
            "Bitte `ENABLE_TESLA_FLEET_OAUTH=true`, `TESLA_CLIENT_ID` und `TESLA_CLIENT_SECRET` setzen."
        )

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    query = parse.urlencode(
        {
            "response_type": "code",
            "client_id": settings.tesla_client_id,
            "redirect_uri": _redirect_uri(settings),
            "scope": settings.tesla_oauth_scope,
            "state": state,
            "nonce": nonce,
            "prompt_missing_scopes": "true",
            "require_requested_scopes": "true",
        }
    )
    return OAuthAuthorizationRequest(url=f"{TESLA_AUTHORIZE_URL}?{query}", state=state, nonce=nonce)


class TeslaFleetApiClient:
    """Official Tesla Fleet OAuth and API client."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def exchange_authorization_code(self, code: str) -> FleetTokenBundle:
        response = self._post_form(
            TESLA_TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "client_id": self.settings.tesla_client_id,
                "client_secret": self.settings.tesla_client_secret,
                "code": code,
                "audience": self.settings.tesla_fleet_api_base_url,
                "redirect_uri": _redirect_uri(self.settings),
                "scope": self.settings.tesla_oauth_scope,
            },
            request_label="Tesla OAuth code exchange",
        )
        payload = self._json_response(response, request_label="Tesla OAuth code exchange")
        if response.status != 200:
            raise TeslaAuthenticationError(
                "Tesla OAuth-Codeaustausch ist fehlgeschlagen. "
                f"HTTP-Status: {response.status}. Antwort: {self._short_payload(payload)}"
            )
        return self._build_token_bundle(payload, fallback_fleet_base_url=self.settings.tesla_fleet_api_base_url)

    def refresh_access_token(self, account: TeslaAccount) -> str:
        refresh_token = decrypt_secret(account.refresh_token)
        access_token = decrypt_secret(account.access_token)

        if access_token and account.expires_at and account.expires_at.timestamp() - TOKEN_REFRESH_SKEW_SECONDS >= time.time():
            return access_token

        if not refresh_token:
            raise TeslaAuthenticationError(
                "Fuer dieses Tesla-Konto ist kein gueltiges Refresh-Token gespeichert. "
                "Bitte den Tesla-Login erneut durchlaufen."
            )

        response = self._post_form(
            TESLA_TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "client_id": self.settings.tesla_client_id,
                "client_secret": self.settings.tesla_client_secret,
                "refresh_token": refresh_token,
            },
            request_label="Tesla OAuth token refresh",
        )
        payload = self._json_response(response, request_label="Tesla OAuth token refresh")
        if response.status != 200:
            raise TeslaAuthenticationError(
                "Tesla Refresh-Token konnte nicht erneuert werden. "
                f"HTTP-Status: {response.status}. Antwort: {self._short_payload(payload)}"
            )

        token_bundle = self._build_token_bundle(
            payload,
            fallback_fleet_base_url=account.fleet_api_base_url or self.settings.tesla_fleet_api_base_url,
        )
        account.access_token = encrypt_secret(token_bundle.access_token)
        account.refresh_token = encrypt_secret(token_bundle.refresh_token or refresh_token)
        account.expires_at = token_bundle.expires_at
        account.fleet_api_base_url = token_bundle.fleet_api_base_url
        account.oauth_scope = token_bundle.scope or account.oauth_scope
        account.last_error = None
        return token_bundle.access_token

    def fetch_user_profile(self, access_token: str, fleet_api_base_url: str | None = None) -> dict[str, Any]:
        response = self._api_request(
            access_token,
            fleet_api_base_url or self.settings.tesla_fleet_api_base_url,
            "/api/1/users/me",
        )
        self._raise_for_api_error(response, request_label="Tesla users/me")
        return self._json_response(response, request_label="Tesla users/me")

    def fetch_region(self, access_token: str, fleet_api_base_url: str | None = None) -> dict[str, Any]:
        response = self._api_request(
            access_token,
            fleet_api_base_url or self.settings.tesla_fleet_api_base_url,
            "/api/1/users/region",
        )
        self._raise_for_api_error(response, request_label="Tesla users/region")
        return self._json_response(response, request_label="Tesla users/region")

    def fetch_vehicles(self, account: TeslaAccount) -> list[FleetVehicleInfo]:
        response = self._api_request(
            self.refresh_access_token(account),
            account.fleet_api_base_url or self.settings.tesla_fleet_api_base_url,
            "/api/1/vehicles",
        )
        self._raise_for_api_error(response, request_label="Tesla vehicles")
        payload = self._json_response(response, request_label="Tesla vehicles")
        vehicle_rows = _extract_list_payload(payload, VEHICLE_RESULT_KEYS)
        vehicles: list[FleetVehicleInfo] = []
        for row in vehicle_rows:
            if not isinstance(row, dict):
                continue
            vin = _text(row.get("vin"))
            if not vin:
                continue
            vehicles.append(
                FleetVehicleInfo(
                    vin=validate_vin(vin),
                    display_name=_text(row.get("display_name")) or _text(row.get("vehicle_name")) or f"Tesla {vin[-4:]}",
                    model=_text(row.get("car_type")) or _text(row.get("model")) or "Tesla",
                    tesla_vehicle_id=_text(row.get("id_s")) or _text(row.get("vehicle_id")) or f"fleet-{vin.lower()}",
                )
            )
        return vehicles

    def list_recent_sessions(self, account: TeslaAccount, vehicle_vin: str) -> list[ChargingSession]:
        response = self._api_request(
            self.refresh_access_token(account),
            account.fleet_api_base_url or self.settings.tesla_fleet_api_base_url,
            "/api/1/dx/charging/history",
        )
        self._raise_for_api_error(response, request_label="Tesla charging history")
        payload = self._json_response(response, request_label="Tesla charging history")
        return parse_fleet_charging_history(payload, requested_vin=vehicle_vin)

    def download_invoice_pdf(self, account: TeslaAccount, invoice_id: str) -> bytes:
        response = self._api_request(
            self.refresh_access_token(account),
            account.fleet_api_base_url or self.settings.tesla_fleet_api_base_url,
            f"/api/1/dx/charging/invoice/{invoice_id}",
            accept="application/pdf",
        )
        content_type = response.headers.get("Content-Type", "")
        if response.status != 200:
            if response.status == 412:
                raise TeslaAuthenticationError(
                    "Tesla Fleet API lehnt die Anfrage mit 412 ab. "
                    "Bitte pruefe im Tesla Developer Portal, ob deine Partner-App fuer diese Region registriert wurde."
                )
            raise InvoiceDownloadError(
                f"Tesla-Rechnung {invoice_id} konnte nicht geladen werden. "
                f"HTTP-Status: {response.status}. Antwort-Auszug: {response.body[:200]!r}"
            )
        if "pdf" not in content_type.lower() and not response.body.startswith(b"%PDF"):
            raise InvoiceDownloadError(
                f"Tesla lieferte fuer Rechnung {invoice_id} keinen PDF-Inhalt zurueck "
                f"(Content-Type: {content_type or 'unbekannt'})."
            )
        return response.body

    def _api_request(self, access_token: str, base_url: str, path: str, *, accept: str = "application/json") -> _HttpResponse:
        request_object = request.Request(
            f"{base_url.rstrip('/')}{path}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": accept,
                "Content-Type": "application/json",
                "User-Agent": "TeslaInvoiceAutomatic/1.1",
            },
            method="GET",
        )
        return self._send_request(request_object, request_label=path)

    def _post_form(self, url: str, payload: dict[str, str], *, request_label: str) -> _HttpResponse:
        encoded_payload = parse.urlencode(payload).encode("utf-8")
        request_object = request.Request(
            url,
            data=encoded_payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "TeslaInvoiceAutomatic/1.1",
            },
            method="POST",
        )
        return self._send_request(request_object, request_label=request_label)

    def _send_request(self, request_object: request.Request, *, request_label: str) -> _HttpResponse:
        try:
            with request.urlopen(request_object, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
                return _HttpResponse(
                    status=getattr(response, "status", 200),
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except error.HTTPError as err:
            return _HttpResponse(
                status=err.code,
                headers=dict(err.headers.items()) if err.headers else {},
                body=err.read(),
            )
        except error.URLError as err:
            raise TeslaApiError(
                f"Tesla konnte fuer {request_label} nicht erreicht werden. "
                f"Bitte DNS, Internet-Zugriff und Firewall des Containers pruefen. Fehler: {err.reason}"
            ) from err

    def _json_response(self, response: _HttpResponse, *, request_label: str) -> dict[str, Any]:
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as err:
            raise TeslaApiError(
                f"Tesla lieferte fuer {request_label} kein gueltiges JSON. Antwort-Auszug: {response.body[:240]!r}"
            ) from err
        if not isinstance(payload, dict):
            raise TeslaApiError(
                f"Tesla lieferte fuer {request_label} ein unerwartetes JSON-Format. Erwartet wurde ein Objekt."
            )
        return payload

    def _build_token_bundle(self, payload: dict[str, Any], *, fallback_fleet_base_url: str) -> FleetTokenBundle:
        access_token = _text(payload.get("access_token"))
        refresh_token = _text(payload.get("refresh_token"))
        token_type = _text(payload.get("token_type")) or "Bearer"
        expires_in = int(payload.get("expires_in") or 28800)
        if not access_token:
            raise TeslaAuthenticationError("Tesla OAuth-Antwort enthaelt kein access_token.")
        expires_at = datetime.fromtimestamp(time.time() + expires_in, tz=timezone.utc)
        return FleetTokenBundle(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            fleet_api_base_url=fallback_fleet_base_url.rstrip("/"),
            token_type=token_type,
            scope=_text(payload.get("scope")),
        )

    def _short_payload(self, payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=True)[:300] if isinstance(payload, (dict, list)) else str(payload)[:300]

    def _raise_for_api_error(self, response: _HttpResponse, *, request_label: str) -> None:
        if response.status < 400:
            return
        if response.status == 401:
            raise TeslaAuthenticationError(
                f"Tesla meldet fuer {request_label} einen Authentifizierungsfehler (401). "
                "Bitte den Tesla-Login erneut verbinden."
            )
        if response.status == 412:
            raise TeslaAuthenticationError(
                f"Tesla lehnt {request_label} mit 412 ab. "
                "Bitte pruefe im Tesla Developer Portal, ob deine Partner-App fuer diese Region registriert wurde."
            )
        raise TeslaApiError(
            f"Tesla Fleet API lieferte fuer {request_label} einen Fehler. "
            f"HTTP-Status: {response.status}. Antwort-Auszug: {response.body[:240]!r}"
        )


def parse_fleet_charging_history(payload: dict[str, Any], *, requested_vin: str) -> list[ChargingSession]:
    """Normalize Tesla Fleet charging history into internal invoice sessions.

    This parser is intentionally defensive because Tesla documents the endpoint names,
    but not a full example payload for every field combination.
    """

    normalized_vin = validate_vin(requested_vin)
    rows = _extract_list_payload(payload, CHARGING_RESULT_KEYS)
    sessions: list[ChargingSession] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        row_vin = _text(row.get("vin")) or _text(row.get("vehicle_vin"))
        if row_vin and row_vin.upper() != normalized_vin:
            continue

        charge_started_at = (
            _parse_datetime(row.get("charge_start_date_time"))
            or _parse_datetime(row.get("chargeStartDateTime"))
            or _parse_datetime(row.get("chargeStopDateTime"))
            or _parse_datetime(row.get("unlatchDateTime"))
            or datetime.now(timezone.utc)
        )
        location = _text(row.get("siteLocationName")) or _text(row.get("siteName")) or _text(row.get("location")) or "Tesla Supercharger"

        invoice_candidates = row.get("invoices")
        if isinstance(invoice_candidates, list) and invoice_candidates:
            for invoice in invoice_candidates:
                if not isinstance(invoice, dict):
                    continue
                invoice_id = _text(invoice.get("id")) or _text(invoice.get("invoice_id")) or _text(invoice.get("contentId"))
                if not invoice_id:
                    continue
                amount = _extract_amount(invoice, row)
                currency = _extract_currency(invoice, row)
                sessions.append(
                    ChargingSession(
                        invoice_id=invoice_id,
                        started_at=charge_started_at,
                        amount=amount,
                        currency=currency,
                        location=location,
                    )
                )
            continue

        invoice_id = _text(row.get("invoice_id")) or _text(row.get("invoiceId")) or _text(row.get("id"))
        if not invoice_id:
            continue
        sessions.append(
            ChargingSession(
                invoice_id=invoice_id,
                started_at=charge_started_at,
                amount=_extract_amount(row),
                currency=_extract_currency(row),
                location=location,
            )
        )

    sessions.sort(key=lambda item: item.started_at, reverse=True)
    return sessions


def _extract_list_payload(payload: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    if isinstance(payload.get("response"), list):
        return payload["response"]
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested_response = value.get("response")
            if isinstance(nested_response, list):
                return nested_response
    return []


def _extract_amount(*mappings: dict[str, Any]) -> Decimal:
    for mapping in mappings:
        for key in AMOUNT_CANDIDATE_KEYS:
            if key not in mapping:
                continue
            parsed_value = _parse_decimal(mapping.get(key))
            if parsed_value is not None:
                return parsed_value
        for value in mapping.values():
            if isinstance(value, dict):
                parsed_value = _parse_decimal(value.get("amount") or value.get("value"))
                if parsed_value is not None:
                    return parsed_value
    return Decimal("0.00")


def _extract_currency(*mappings: dict[str, Any]) -> str:
    for mapping in mappings:
        for key in ("currency", "currency_code", "currencyCode", "displayCurrency"):
            currency = _text(mapping.get(key))
            if currency:
                return currency.upper()
        for value in mapping.values():
            if isinstance(value, dict):
                currency = _text(value.get("currency") or value.get("currencyCode"))
                if currency:
                    return currency.upper()
    return DEFAULT_CURRENCY


def _parse_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace(",", ".")
    try:
        return Decimal(text)
    except Exception:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed_value = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed_value if parsed_value.tzinfo else parsed_value.replace(tzinfo=timezone.utc)


def _redirect_uri(settings: Settings) -> str:
    return f"{settings.app_base_url.rstrip('/')}{settings.tesla_oauth_redirect_path}"


def _text(value: Any) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None
