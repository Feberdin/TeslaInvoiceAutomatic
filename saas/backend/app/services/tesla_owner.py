"""
Purpose: Connect the SaaS app to Tesla's owner/mobile charging endpoints for real invoice downloads.
Input/Output: Accepts imported Tesla tokens, refreshes them when required, fetches charging history per VIN and downloads invoice PDFs.
Invariants: Access and refresh tokens are never logged, invoice IDs come from Tesla `contentId`, and every live request uses the stored VIN plus locale parameters.
Debug: If live sync fails, first check whether token refresh succeeds, then inspect the stored VIN, Tesla base URLs and the last API status code mentioned in the raised error.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from urllib import error, parse, request

from app.domain import ChargingSession
from app.errors import InvoiceDownloadError, TeslaApiError, TeslaAuthenticationError, TeslaTokenImportError
from app.token_store import decrypt_secret, encrypt_secret
from app.utils import normalize_email, validate_vin

if TYPE_CHECKING:
    from app.models import TeslaAccount, Vehicle


DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_AUTH_BASE_URL = "https://auth.tesla.com"
DEFAULT_OWNERSHIP_BASE_URL = "https://ownership.tesla.com/mobile-app/charging"
FALLBACK_OWNERSHIP_BASE_URLS = (
    DEFAULT_OWNERSHIP_BASE_URL,
    "https://owner-api.teslamotors.com/bff/v2/mobile-app/charging",
)
DEFAULT_DEVICE_LANGUAGE = "de"
DEFAULT_DEVICE_COUNTRY = "DE"
DEFAULT_HTTP_LOCALE = "de_DE"
TOKEN_REFRESH_SKEW_SECONDS = 300
DEFAULT_CURRENCY = "EUR"
AMOUNT_KEYS = (
    "amount",
    "totalAmount",
    "invoiceAmount",
    "price",
    "totalCost",
    "cost",
    "chargeCost",
    "totalChargedAmount",
)
FLOAT_PATTERN = re.compile(r"-?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class ImportedTeslaTokens:
    tesla_account_email: str
    access_token: str | None
    refresh_token: str | None
    expires_at: datetime | None
    auth_base_url: str


@dataclass(frozen=True)
class _TeslaHttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def import_tokens_from_cache_json(raw_cache_json: str, tesla_account_email: str) -> ImportedTeslaTokens:
    """Parse a TeslaPy or tesla_ha cache JSON payload into normalized token data.

    Accepted input:
        - full cache.json content with one or multiple Tesla accounts
        - one already-selected Tesla account object containing `sso`
    """

    normalized_email = normalize_email(tesla_account_email)
    try:
        payload = json.loads(raw_cache_json)
    except ValueError as err:
        raise TeslaTokenImportError(
            "Der eingefuegte Tesla-Cache ist kein gueltiges JSON. "
            "Bitte den kompletten Inhalt der TeslaPy-/tesla_ha-`cache.json` einfuegen."
        ) from err

    if not isinstance(payload, dict):
        raise TeslaTokenImportError(
            "Der eingefuegte Tesla-Cache muss ein JSON-Objekt sein. "
            "Bitte den kompletten `cache.json`-Inhalt oder ein einzelnes Account-Objekt einfuegen."
        )

    account_email, account_payload = _extract_cache_account(payload, normalized_email)
    sso_payload = account_payload.get("sso")
    if not isinstance(sso_payload, dict):
        raise TeslaTokenImportError(
            "Im eingefuegten Tesla-Cache fehlen die `sso`-Daten. "
            "Bitte den Tesla-Login in TeslaPy/tesla_ha erneuern und den Cache erneut einfuegen."
        )

    access_token = _normalized_optional_string(sso_payload.get("access_token"))
    refresh_token = _normalized_optional_string(sso_payload.get("refresh_token"))
    if not access_token and not refresh_token:
        raise TeslaTokenImportError(
            "Im Tesla-Cache fehlen access_token und refresh_token. "
            "Bitte den Tesla-Login neu durchfuehren und den aktuellen Cache einfuegen."
        )

    return ImportedTeslaTokens(
        tesla_account_email=account_email,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=_parse_expiry_to_datetime(sso_payload.get("expires_at"), access_token),
        auth_base_url=_normalize_url(account_payload.get("url"), DEFAULT_AUTH_BASE_URL),
    )


def build_imported_tokens(
    *,
    tesla_account_email: str,
    cache_json: str | None,
    access_token: str | None,
    refresh_token: str | None,
    auth_base_url: str | None = None,
) -> ImportedTeslaTokens:
    """Build token data from either a cache JSON import or manually entered tokens."""

    if cache_json and cache_json.strip():
        return import_tokens_from_cache_json(cache_json, tesla_account_email)

    normalized_email = normalize_email(tesla_account_email)
    normalized_access = _normalized_optional_string(access_token)
    normalized_refresh = _normalized_optional_string(refresh_token)
    if not normalized_access and not normalized_refresh:
        raise TeslaTokenImportError(
            "Bitte entweder den TeslaPy-/tesla_ha-Cache einfuegen oder mindestens ein Tesla-Refresh-Token angeben."
        )

    return ImportedTeslaTokens(
        tesla_account_email=normalized_email,
        access_token=normalized_access,
        refresh_token=normalized_refresh,
        expires_at=_parse_expiry_to_datetime(None, normalized_access),
        auth_base_url=_normalize_url(auth_base_url, DEFAULT_AUTH_BASE_URL),
    )


def parse_owner_charging_sessions(payload: Any, *, requested_vin: str) -> list[ChargingSession]:
    """Convert Tesla charging-history JSON into the generic session model used by the SaaS sync."""

    normalized_vin = validate_vin(requested_vin)
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []

    sessions: list[ChargingSession] = []
    for session in data:
        if not isinstance(session, dict):
            continue

        session_vin = _normalized_optional_string(session.get("vin"))
        if session_vin and session_vin.upper() != normalized_vin:
            continue

        charged_at = (
            _parse_datetime(
                session.get("unlatchDateTime")
                or session.get("chargeStopDateTime")
                or session.get("chargeStartDateTime")
            )
            or datetime.now(timezone.utc)
        )
        location = _normalized_optional_string(session.get("siteLocationName") or session.get("siteName")) or "Tesla Supercharger"

        for invoice in session.get("invoices") or []:
            if not isinstance(invoice, dict):
                continue
            content_id = _normalized_optional_string(invoice.get("contentId"))
            file_name = _normalized_optional_string(invoice.get("fileName"))
            if not content_id or not file_name:
                continue
            amount, currency = _extract_amount_and_currency(invoice, session)
            sessions.append(
                ChargingSession(
                    invoice_id=content_id,
                    started_at=charged_at,
                    amount=amount,
                    currency=currency,
                    location=location,
                )
            )

    sessions.sort(key=lambda item: item.started_at, reverse=True)
    return sessions


class TeslaOwnerApiClient:
    """Synchronous Tesla owner/mobile charging client for the FastAPI worker and API routes."""

    def ensure_valid_access_token(self, account: TeslaAccount) -> str:
        access_token = decrypt_secret(account.access_token)
        refresh_token = decrypt_secret(account.refresh_token)
        expires_at = account.expires_at

        if access_token and expires_at:
            expires_at_epoch = expires_at.timestamp()
            if expires_at_epoch - TOKEN_REFRESH_SKEW_SECONDS >= time.time():
                return access_token

        if access_token and not refresh_token:
            decoded_expiry = _parse_expiry_to_datetime(None, access_token)
            if decoded_expiry and decoded_expiry.timestamp() - TOKEN_REFRESH_SKEW_SECONDS >= time.time():
                account.expires_at = decoded_expiry
                return access_token

        if not refresh_token:
            raise TeslaAuthenticationError(
                "Es ist kein gueltiges Tesla-Refresh-Token gespeichert. "
                "Bitte die Tesla-Verbindung im Dashboard erneut speichern."
            )

        return self._refresh_tokens(account, refresh_token)

    def list_recent_sessions(self, account: TeslaAccount, vehicle: Vehicle) -> list[ChargingSession]:
        payload = self._request_json(
            account,
            "history",
            params={
                **self._build_invoice_query_params(account, vehicle),
                "operationName": "getChargingHistoryV2",
            },
        )
        return parse_owner_charging_sessions(payload, requested_vin=vehicle.vin)

    def download_invoice_pdf(
        self,
        account: TeslaAccount,
        invoice_id: str,
        vehicle: Vehicle,
        amount: Decimal,
        currency: str,
        location: str,
    ) -> bytes:
        if not invoice_id:
            raise InvoiceDownloadError("Tesla contentId fehlt. Ohne contentId kann kein Rechnungs-PDF geladen werden.")

        response = self._request(
            account,
            "GET",
            f"invoice/{invoice_id}",
            params=self._build_invoice_query_params(account, vehicle),
            expect_pdf=True,
        )
        content_type = response.headers.get("Content-Type", "")
        if response.status != 200:
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

    def _request_json(self, account: TeslaAccount, path_suffix: str, *, params: dict[str, str]) -> dict[str, Any]:
        response = self._request(account, "GET", path_suffix, params=params, expect_pdf=False)
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as err:
            raise TeslaApiError(
                f"Tesla lieferte fuer {path_suffix} kein gueltiges JSON. "
                f"Antwort-Auszug: {response.body[:300]!r}"
            ) from err

        if response.status >= 400:
            raise TeslaApiError(
                f"Tesla lieferte fuer {path_suffix} einen Fehler. "
                f"HTTP-Status: {response.status}. Antwort: {json.dumps(payload, ensure_ascii=True)[:300]}"
            )
        if not isinstance(payload, dict):
            raise TeslaApiError(
                f"Tesla lieferte fuer {path_suffix} ein unerwartetes Datenformat. Erwartet wurde ein JSON-Objekt."
            )
        return payload

    def _request(
        self,
        account: TeslaAccount,
        method: str,
        path_suffix: str,
        *,
        params: dict[str, str],
        expect_pdf: bool,
    ) -> _TeslaHttpResponse:
        access_token = self.ensure_valid_access_token(account)
        last_fallback_error: str | None = None

        for base_url in self._candidate_base_urls(account):
            response = self._send(
                method,
                url=f"{base_url.rstrip('/')}/{path_suffix}",
                access_token=access_token,
                params=params,
                expect_pdf=expect_pdf,
            )
            if response.status == 401:
                access_token = self._refresh_tokens(account, decrypt_secret(account.refresh_token))
                response = self._send(
                    method,
                    url=f"{base_url.rstrip('/')}/{path_suffix}",
                    access_token=access_token,
                    params=params,
                    expect_pdf=expect_pdf,
                )
                if response.status == 401:
                    raise TeslaAuthenticationError(
                        f"Tesla lehnt das gespeicherte Owner-Token fuer {path_suffix} auch nach Refresh ab. "
                        "Bitte die Tesla-Verbindung im Dashboard erneuern."
                    )

            if response.status not in (404, 405):
                return response

            last_fallback_error = (
                f"Pfad {path_suffix} unter {base_url} antwortete mit HTTP {response.status}: {response.body[:200]!r}"
            )

        raise TeslaApiError(
            "Tesla lieferte fuer die Charging-Endpunkte keinen funktionierenden Pfad. "
            f"Letzter Fehler: {last_fallback_error or 'unbekannt'}"
        )

    def _send(
        self,
        method: str,
        *,
        url: str,
        access_token: str,
        params: dict[str, str],
        expect_pdf: bool,
    ) -> _TeslaHttpResponse:
        query = parse.urlencode({key: value for key, value in params.items() if value})
        final_url = f"{url}?{query}" if query else url
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Tesla-User-Agent": "TeslaApp/4.10.0",
            "User-Agent": "TeslaInvoiceAutomatic/1.0",
            "Accept": "application/pdf" if expect_pdf else "application/json",
        }
        request_object = request.Request(final_url, headers=headers, method=method)
        return self._send_request(request_object, request_label=final_url)

    def _refresh_tokens(self, account: TeslaAccount, refresh_token: str | None) -> str:
        normalized_refresh_token = _normalized_optional_string(refresh_token)
        if not normalized_refresh_token:
            raise TeslaAuthenticationError(
                "Im Tesla-Konto fehlt ein refresh_token. Bitte den Tesla-Login neu importieren."
            )

        auth_base_url = _normalize_url(account.auth_base_url, DEFAULT_AUTH_BASE_URL)
        payload = json.dumps(
            {
                "grant_type": "refresh_token",
                "client_id": "ownerapi",
                "refresh_token": normalized_refresh_token,
                "scope": "openid email offline_access",
            }
        ).encode("utf-8")
        request_object = request.Request(
            f"{auth_base_url}/oauth2/v3/token",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        response = self._send_request(request_object, request_label="Tesla OAuth token refresh")
        try:
            response_payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as err:
            raise TeslaAuthenticationError(
                "Tesla OAuth-Refresh lieferte keine gueltige JSON-Antwort."
            ) from err

        if response.status != 200:
            raise TeslaAuthenticationError(
                "Tesla OAuth-Refresh fehlgeschlagen. "
                f"HTTP-Status: {response.status}. Antwort: {json.dumps(response_payload, ensure_ascii=True)[:300]}"
            )

        access_token = _normalized_optional_string(response_payload.get("access_token"))
        new_refresh_token = _normalized_optional_string(response_payload.get("refresh_token")) or normalized_refresh_token
        expires_in = int(response_payload.get("expires_in") or 28800)
        if not access_token:
            raise TeslaAuthenticationError(
                "Tesla OAuth-Antwort enthaelt kein access_token. Bitte die Tesla-Verbindung erneut speichern."
            )

        account.access_token = encrypt_secret(access_token)
        account.refresh_token = encrypt_secret(new_refresh_token)
        account.expires_at = datetime.fromtimestamp(time.time() + expires_in, tz=timezone.utc)
        account.last_error = None
        return access_token

    def _send_request(self, request_object: request.Request, *, request_label: str) -> _TeslaHttpResponse:
        try:
            with request.urlopen(request_object, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
                return _TeslaHttpResponse(
                    status=getattr(response, "status", 200),
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except error.HTTPError as err:
            return _TeslaHttpResponse(
                status=err.code,
                headers=dict(err.headers.items()) if err.headers else {},
                body=err.read(),
            )
        except error.URLError as err:
            raise TeslaApiError(
                f"Tesla konnte fuer {request_label} nicht erreicht werden. "
                f"Bitte Netzwerk, DNS und Internet-Zugriff des Containers pruefen. Fehler: {err.reason}"
            ) from err

    def _build_invoice_query_params(self, account: TeslaAccount, vehicle: Vehicle) -> dict[str, str]:
        return {
            "vin": validate_vin(vehicle.vin),
            "deviceLanguage": _normalized_optional_string(account.device_language) or DEFAULT_DEVICE_LANGUAGE,
            "deviceCountry": _normalized_optional_string(account.device_country) or DEFAULT_DEVICE_COUNTRY,
            "httpLocale": _normalized_optional_string(account.http_locale) or DEFAULT_HTTP_LOCALE,
        }

    def _candidate_base_urls(self, account: TeslaAccount) -> list[str]:
        configured = _normalize_url(account.ownership_base_url, DEFAULT_OWNERSHIP_BASE_URL)
        unique_candidates: list[str] = []
        for candidate in (configured, *FALLBACK_OWNERSHIP_BASE_URLS):
            normalized_candidate = candidate.rstrip("/")
            if normalized_candidate and normalized_candidate not in unique_candidates:
                unique_candidates.append(normalized_candidate)
        return unique_candidates


def _extract_cache_account(payload: dict[str, Any], normalized_email: str) -> tuple[str, dict[str, Any]]:
    if isinstance(payload.get("sso"), dict):
        return normalized_email, payload

    for key, value in payload.items():
        if isinstance(key, str) and key.lower() == normalized_email and isinstance(value, dict):
            return normalize_email(key), value

    cache_entries = [(key, value) for key, value in payload.items() if isinstance(key, str) and isinstance(value, dict)]
    entries_with_sso = [(key, value) for key, value in cache_entries if isinstance(value.get("sso"), dict)]
    if len(entries_with_sso) == 1:
        key, value = entries_with_sso[0]
        return normalize_email(key), value

    raise TeslaTokenImportError(
        "Im eingefuegten Tesla-Cache wurde kein passender Tesla-Account gefunden. "
        "Bitte die Tesla-Konto-E-Mail pruefen oder nur den passenden Account-Eintrag einfuegen."
    )


def _parse_expiry_to_datetime(raw_expiry: Any, access_token: str | None) -> datetime | None:
    expiry_timestamp = 0.0
    if raw_expiry not in (None, ""):
        try:
            expiry_timestamp = float(raw_expiry)
        except (TypeError, ValueError):
            expiry_timestamp = 0.0

    if not expiry_timestamp and access_token:
        jwt_parts = access_token.split(".")
        if len(jwt_parts) == 3:
            payload = jwt_parts[1]
            payload += "=" * ((4 - len(payload) % 4) % 4)
            try:
                decoded = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
            except Exception:
                decoded = {}
            try:
                expiry_timestamp = float(decoded.get("exp") or 0)
            except (TypeError, ValueError):
                expiry_timestamp = 0.0

    if not expiry_timestamp:
        return None
    return datetime.fromtimestamp(expiry_timestamp, tz=timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed_value = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed_value if parsed_value.tzinfo else parsed_value.replace(tzinfo=timezone.utc)


def _extract_amount_and_currency(invoice_payload: dict[str, Any], session_payload: dict[str, Any]) -> tuple[Decimal, str]:
    for candidate_payload in (invoice_payload, session_payload):
        amount, currency = _extract_amount_from_mapping(candidate_payload)
        if amount is not None:
            return amount, currency or DEFAULT_CURRENCY

    return Decimal("0.00"), DEFAULT_CURRENCY


def _extract_amount_from_mapping(mapping: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    for key in AMOUNT_KEYS:
        if key not in mapping:
            continue
        amount_value, currency_value = _coerce_amount_value(mapping.get(key))
        if amount_value is not None:
            detected_currency = currency_value or _detect_currency(mapping)
            return amount_value, detected_currency
    nested_currency = _detect_currency(mapping)
    for value in mapping.values():
        if isinstance(value, dict):
            amount_value, currency_value = _coerce_amount_value(value)
            if amount_value is not None:
                return amount_value, currency_value or nested_currency
    return None, nested_currency


def _coerce_amount_value(value: Any) -> tuple[Decimal | None, str | None]:
    if isinstance(value, dict):
        for nested_key in ("amount", "value", "cost", "price"):
            if nested_key in value:
                nested_amount = _parse_decimal(value.get(nested_key))
                if nested_amount is not None:
                    return nested_amount, _detect_currency(value)
        return None, _detect_currency(value)

    parsed_amount = _parse_decimal(value)
    return parsed_amount, _detect_currency(value)


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = str(value).strip()
    if not text:
        return None

    matched = FLOAT_PATTERN.search(text)
    if matched is None:
        return None
    normalized = matched.group(0)
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _detect_currency(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("currency", "currencyCode", "displayCurrency"):
            if key in value:
                detected = _detect_currency(value.get(key))
                if detected:
                    return detected
        return None

    text = str(value or "").strip().upper()
    if not text:
        return None
    if "EUR" in text or "€" in text:
        return "EUR"
    if "USD" in text or "$" in text:
        return "USD"
    if "GBP" in text or "£" in text:
        return "GBP"
    if len(text) == 3 and text.isalpha():
        return text
    return None


def _normalize_url(value: Any, default: str) -> str:
    normalized = str(value or default).strip()
    if not normalized:
        return default
    return normalized.rstrip("/")


def _normalized_optional_string(value: Any) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None
