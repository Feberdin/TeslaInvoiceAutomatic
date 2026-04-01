"""
Purpose: Handle operator-only Tesla Fleet partner onboarding such as key generation, public-key hosting and partner registration.
Input/Output: Reads app settings plus files in `/data`, talks to Tesla's partner endpoints and returns status snapshots for the admin UI.
Invariants: The public key always uses the Tesla-required `prime256v1` curve, the private key never leaves the server, and partner registration only runs with explicit operator action.
Debug: If Fleet OAuth works but `users/me` returns 412, inspect the generated public key, the hosted well-known URL and the last register/verify status from this module.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import Settings
from app.errors import TeslaApiError, TeslaAuthenticationError
from app.services.tesla_fleet import TESLA_TOKEN_URL, tesla_oauth_available


PUBLIC_KEY_WELL_KNOWN_PATH = "/.well-known/appspecific/com.tesla.3p.public-key.pem"
KEY_DIRECTORY_NAME = "tesla_partner"
PRIVATE_KEY_FILE_NAME = "private-key.pem"
PUBLIC_KEY_FILE_NAME = "com.tesla.3p.public-key.pem"
STATE_FILE_NAME = "partner_registration_state.json"
DEFAULT_TIMEOUT_SECONDS = 30
SUCCESS_REGISTER_CODES = {200, 201, 202, 204}


@dataclass(frozen=True)
class FleetPartnerAdminStatus:
    app_base_url: str
    app_domain: str
    callback_url: str
    fleet_api_base_url: str
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


@dataclass(frozen=True)
class FleetPartnerActionResult:
    status: str
    message: str
    http_status: int | None = None


@dataclass(frozen=True)
class _HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class TeslaPartnerAdminService:
    """Provide the operator-facing Tesla Fleet partner setup helpers."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._key_dir = settings.data_dir / KEY_DIRECTORY_NAME
        self._private_key_path = self._key_dir / PRIVATE_KEY_FILE_NAME
        self._public_key_path = self._key_dir / PUBLIC_KEY_FILE_NAME
        self._state_path = self._key_dir / STATE_FILE_NAME

    def current_status(self) -> FleetPartnerAdminStatus:
        """Return a status snapshot for the admin UI without mutating state."""

        state = self._load_state()
        public_key_pem = self.public_key_pem()
        return FleetPartnerAdminStatus(
            app_base_url=self.settings.app_base_url.rstrip("/"),
            app_domain=self.app_domain(),
            callback_url=f"{self.settings.app_base_url.rstrip('/')}{self.settings.tesla_oauth_redirect_path}",
            fleet_api_base_url=self.settings.tesla_fleet_api_base_url,
            oauth_ready=tesla_oauth_available(self.settings),
            register_ready=tesla_oauth_available(self.settings) and bool(public_key_pem),
            public_key_url=self.public_key_url(),
            public_key_present=bool(public_key_pem),
            private_key_present=self._private_key_path.exists(),
            public_key_pem=public_key_pem,
            public_key_fingerprint=self._public_key_fingerprint(public_key_pem),
            key_generated_at=state.get("key_generated_at"),
            partner_token_scope=self.settings.tesla_partner_token_scope,
            last_register_status=state.get("last_register_status", "not_started"),
            last_register_message=state.get("last_register_message"),
            last_register_http_status=self._safe_int(state.get("last_register_http_status")),
            last_register_attempt_at=state.get("last_register_attempt_at"),
            last_register_success_at=state.get("last_register_success_at"),
            last_verify_status=state.get("last_verify_status", "not_started"),
            last_verify_message=state.get("last_verify_message"),
            last_verify_http_status=self._safe_int(state.get("last_verify_http_status")),
            last_verify_at=state.get("last_verify_at"),
        )

    def public_key_pem(self) -> str | None:
        """Return the stored PEM-encoded public key or `None` when it does not exist yet."""

        if not self._public_key_path.exists():
            return None
        pem_text = self._public_key_path.read_text(encoding="utf-8").strip()
        return pem_text or None

    def generate_key_pair(self, *, force: bool = False) -> FleetPartnerActionResult:
        """Create or rotate the Tesla-required EC key pair on disk."""

        self._key_dir.mkdir(parents=True, exist_ok=True)
        if (self._private_key_path.exists() or self._public_key_path.exists()) and not force:
            raise ValueError(
                "Es existiert bereits ein Tesla-Fleet-Schluesselpaar. "
                "Wenn du wirklich neu erzeugen willst, bestaetige den Vorgang im Admin-Menue."
            )

        private_key = ec.generate_private_key(ec.SECP256R1())
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        self._private_key_path.write_bytes(private_key_pem)
        self._public_key_path.write_bytes(public_key_pem)
        self._save_state(
            {
                "key_generated_at": self._now_iso(),
                "last_register_status": "stale",
                "last_register_message": (
                    "Der Fleet-Public-Key wurde neu erzeugt. "
                    "Bitte den Tesla-Register-Button erneut ausfuehren, damit Tesla den neuen Key kennt."
                ),
                "last_register_http_status": None,
                "last_verify_status": "stale",
                "last_verify_message": "Der Public-Key wurde neu erzeugt. Bitte Tesla-Status erneut pruefen.",
                "last_verify_http_status": None,
                "last_verify_at": None,
            }
        )
        return FleetPartnerActionResult(
            status="generated",
            message=(
                "Tesla-Fleet-Schluesselpaar wurde erzeugt. "
                "Der Public Key ist jetzt lokal verfuegbar und kann unter der Well-Known-URL ausgeliefert werden."
            ),
        )

    def register_partner_account(self) -> FleetPartnerActionResult:
        """Call Tesla's partner register endpoint for the configured Fleet region."""

        if not tesla_oauth_available(self.settings):
            raise TeslaAuthenticationError(
                "Fleet OAuth ist noch nicht vollstaendig konfiguriert. "
                "Bitte `TESLA_CLIENT_ID`, `TESLA_CLIENT_SECRET`, `APP_BASE_URL` und die Fleet-Region setzen."
            )
        if not self.public_key_pem():
            raise ValueError(
                "Es ist noch kein Tesla-Fleet-Public-Key vorhanden. "
                "Bitte zuerst im Admin-Menue den Schluessel erzeugen."
            )

        partner_token = self._request_partner_token()
        domain = self.app_domain()
        response = self._request(
            method="POST",
            url=f"{self.settings.tesla_fleet_api_base_url}/api/1/partner_accounts",
            headers={
                "Authorization": f"Bearer {partner_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "TeslaInvoiceAutomatic/1.1",
            },
            body=json.dumps({"domain": domain}).encode("utf-8"),
            request_label="Tesla partner register",
        )

        attempt_timestamp = self._now_iso()
        if response.status in SUCCESS_REGISTER_CODES:
            message = (
                "Tesla hat den Partner-Register-Call akzeptiert. "
                "Pruefe jetzt den Tesla-Status, damit wir sehen, ob der Public Key fuer die Domain bereits sichtbar ist."
            )
            self._save_state(
                {
                    "last_register_status": "success",
                    "last_register_message": message,
                    "last_register_http_status": response.status,
                    "last_register_attempt_at": attempt_timestamp,
                    "last_register_success_at": attempt_timestamp,
                }
            )
            verify_result = self.verify_partner_registration()
            return FleetPartnerActionResult(
                status="success",
                message=f"{message} {verify_result.message}",
                http_status=response.status,
            )

        error_message = self._fleet_error_message("Tesla partner register", response)
        self._save_state(
            {
                "last_register_status": "error",
                "last_register_message": error_message,
                "last_register_http_status": response.status,
                "last_register_attempt_at": attempt_timestamp,
            }
        )
        raise TeslaAuthenticationError(error_message)

    def verify_partner_registration(self) -> FleetPartnerActionResult:
        """Ask Tesla whether a public key is already registered for this application domain."""

        if not tesla_oauth_available(self.settings):
            raise TeslaAuthenticationError(
                "Fleet OAuth ist noch nicht vollstaendig konfiguriert. "
                "Ohne Client ID, Secret und Fleet-Region kann Tesla den Partner-Status nicht pruefen."
            )

        domain = self.app_domain()
        partner_token = self._request_partner_token()
        response = self._request(
            method="GET",
            url=(
                f"{self.settings.tesla_fleet_api_base_url}/api/1/partner_accounts/public_key"
                f"?domain={parse.quote(domain, safe='')}"
            ),
            headers={
                "Authorization": f"Bearer {partner_token}",
                "Accept": "application/json",
                "User-Agent": "TeslaInvoiceAutomatic/1.1",
            },
            request_label="Tesla partner public_key",
        )

        attempt_timestamp = self._now_iso()
        if response.status == 200:
            response_excerpt = self._body_excerpt(response.body)
            local_public_key = self.public_key_pem() or ""
            matching_key = local_public_key.replace("\n", "")[:80] in response_excerpt.replace("\\n", "").replace("\n", "")
            message = (
                "Tesla bestaetigt bereits einen registrierten Public Key fuer diese Domain."
                if matching_key
                else "Tesla liefert bereits einen Public Key fuer diese Domain zurueck."
            )
            self._save_state(
                {
                    "last_verify_status": "registered",
                    "last_verify_message": message,
                    "last_verify_http_status": response.status,
                    "last_verify_at": attempt_timestamp,
                }
            )
            return FleetPartnerActionResult(status="registered", message=message, http_status=response.status)

        if response.status == 404:
            message = (
                "Tesla kennt fuer diese Domain noch keinen registrierten Public Key. "
                "Fuehre jetzt den Partner-Register-Button aus und pruefe danach erneut."
            )
            self._save_state(
                {
                    "last_verify_status": "missing",
                    "last_verify_message": message,
                    "last_verify_http_status": response.status,
                    "last_verify_at": attempt_timestamp,
                }
            )
            return FleetPartnerActionResult(status="missing", message=message, http_status=response.status)

        if response.status == 403:
            message = (
                f"Tesla kennt fuer die Domain `{domain}` aktuell noch keinen freigeschalteten Partner-Zugriff. "
                "Das ist vor dem ersten erfolgreichen Register-Call normal. "
                "Fuehre jetzt den Partner-Register-Button aus und pruefe danach erneut."
            )
            self._save_state(
                {
                    "last_verify_status": "missing",
                    "last_verify_message": message,
                    "last_verify_http_status": response.status,
                    "last_verify_at": attempt_timestamp,
                }
            )
            return FleetPartnerActionResult(status="missing", message=message, http_status=response.status)

        error_message = self._fleet_error_message("Tesla partner public_key", response)
        self._save_state(
            {
                "last_verify_status": "error",
                "last_verify_message": error_message,
                "last_verify_http_status": response.status,
                "last_verify_at": attempt_timestamp,
            }
        )
        raise TeslaAuthenticationError(error_message)

    def app_domain(self) -> str:
        """Return the hostname derived from the configured public base URL."""

        parsed_url = urlparse(self.settings.app_base_url)
        if not parsed_url.hostname:
            raise ValueError(
                "APP_BASE_URL enthaelt keinen gueltigen Hostnamen. "
                "Bitte zum Beispiel `https://tesla-invoice.example.de` setzen."
            )
        return parsed_url.hostname

    def public_key_url(self) -> str:
        return f"{self.settings.app_base_url.rstrip('/')}{PUBLIC_KEY_WELL_KNOWN_PATH}"

    def _request_partner_token(self) -> str:
        response = self._request(
            method="POST",
            url=TESLA_TOKEN_URL,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "TeslaInvoiceAutomatic/1.1",
            },
            body=parse.urlencode(
                {
                    "grant_type": "client_credentials",
                    "client_id": self.settings.tesla_client_id,
                    "client_secret": self.settings.tesla_client_secret,
                    "scope": self.settings.tesla_partner_token_scope,
                    "audience": self.settings.tesla_fleet_api_base_url,
                }
            ).encode("utf-8"),
            request_label="Tesla partner token",
        )
        payload = self._json_payload(response, request_label="Tesla partner token")
        if response.status != 200:
            raise TeslaAuthenticationError(
                "Tesla Partner-Token konnte nicht erstellt werden. "
                f"HTTP-Status: {response.status}. Antwort: {self._short_payload(payload)}"
            )
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise TeslaAuthenticationError("Tesla Partner-Token-Antwort enthaelt kein access_token.")
        return access_token

    def _request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        request_label: str,
        body: bytes | None = None,
    ) -> _HttpResponse:
        request_object = request.Request(url, data=body, headers=headers, method=method)
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

    def _json_payload(self, response: _HttpResponse, *, request_label: str) -> dict[str, Any]:
        if not response.body:
            return {}
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

    def _fleet_error_message(self, request_label: str, response: _HttpResponse) -> str:
        if response.status == 401:
            return (
                f"Tesla meldet fuer {request_label} einen Authentifizierungsfehler (401). "
                "Bitte Client ID, Client Secret und Fleet-Region pruefen."
            )
        if response.status == 412:
            return (
                f"Tesla lehnt {request_label} mit 412 ab. "
                "Das deutet meist darauf hin, dass die Partner-App fuer diese Region noch nicht vollstaendig registriert ist."
            )
        return (
            f"Tesla lieferte fuer {request_label} einen Fehler. "
            f"HTTP-Status: {response.status}. Antwort-Auszug: {self._body_excerpt(response.body)}"
        )

    def _body_excerpt(self, body: bytes) -> str:
        text = body.decode("utf-8", errors="replace").strip()
        return text[:300] if text else "(leer)"

    def _short_payload(self, payload: Any) -> str:
        if isinstance(payload, (dict, list)):
            return json.dumps(payload, ensure_ascii=True)[:300]
        return str(payload)[:300]

    def _public_key_fingerprint(self, pem_text: str | None) -> str | None:
        if not pem_text:
            return None
        digest = hashlib.sha256(pem_text.encode("utf-8")).hexdigest().upper()
        return ":".join(digest[index : index + 2] for index in range(0, len(digest), 2))

    def _load_state(self) -> dict[str, Any]:
        if not self._state_path.exists():
            return {}
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_state(self, patch: dict[str, Any]) -> None:
        self._key_dir.mkdir(parents=True, exist_ok=True)
        current_state = self._load_state()
        current_state.update(patch)
        self._state_path.write_text(json.dumps(current_state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def _safe_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
