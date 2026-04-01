"""
Purpose: Implement Google OAuth for app login and optional Gmail sending with the same account.
Input/Output: Builds Google authorize URLs, exchanges callback codes for tokens, refreshes stored Google tokens and sends RFC822 messages via Gmail API.
Invariants: Google login always resolves to a verified e-mail address, refresh tokens stay encrypted at rest and Gmail sends only run when the `gmail.send` scope is present.
Debug: If Google login or mail sending fails, inspect the configured redirect URI, granted scopes and the exact Google HTTP status before changing the UI.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any
from urllib import error, parse, request

from app.config import Settings
from app.errors import GoogleApiError, GoogleAuthenticationError, TeslaAuthenticationError
from app.token_store import decrypt_secret, encrypt_secret
from app.utils import normalize_email

if TYPE_CHECKING:
    from app.models import GoogleAccount


GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GOOGLE_GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DEFAULT_TIMEOUT_SECONDS = 30
TOKEN_REFRESH_SKEW_SECONDS = 300


@dataclass(frozen=True)
class GoogleAuthorizationRequest:
    url: str
    state: str
    nonce: str


@dataclass(frozen=True)
class GoogleTokenBundle:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scope: str
    id_token: str | None


@dataclass(frozen=True)
class GoogleUserProfile:
    subject: str
    email: str
    email_verified: bool
    name: str | None
    picture_url: str | None


@dataclass(frozen=True)
class _HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def google_oauth_available(settings: Settings) -> bool:
    return bool(
        settings.enable_google_oauth
        and settings.google_client_id
        and settings.google_client_secret
        and settings.app_base_url
    )


def google_gmail_send_available(google_account: "GoogleAccount | None") -> bool:
    if google_account is None:
        return False
    scope = (google_account.oauth_scope or "").strip()
    has_token = bool(google_account.access_token or google_account.refresh_token)
    return has_token and scope_contains(scope, GOOGLE_GMAIL_SEND_SCOPE)


def scope_contains(scope: str, required_scope: str) -> bool:
    return required_scope in {item.strip() for item in (scope or "").split(" ") if item.strip()}


def build_google_authorization_request(settings: Settings) -> GoogleAuthorizationRequest:
    if not google_oauth_available(settings):
        raise GoogleAuthenticationError(
            "Google OAuth ist fuer diese Installation noch nicht konfiguriert. "
            "Bitte `ENABLE_GOOGLE_OAUTH=true`, `GOOGLE_CLIENT_ID` und `GOOGLE_CLIENT_SECRET` setzen."
        )

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    query = parse.urlencode(
        {
            "response_type": "code",
            "client_id": settings.google_client_id,
            "redirect_uri": _redirect_uri(settings),
            "scope": settings.google_oauth_scope,
            "state": state,
            "nonce": nonce,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": settings.google_oauth_prompt,
        }
    )
    return GoogleAuthorizationRequest(url=f"{GOOGLE_AUTHORIZE_URL}?{query}", state=state, nonce=nonce)


class GoogleOAuthClient:
    """Google OAuth helper for login, token refresh and Gmail sending."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def exchange_authorization_code(self, code: str) -> GoogleTokenBundle:
        response = self._post_form(
            GOOGLE_TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "code": code,
                "redirect_uri": _redirect_uri(self.settings),
            },
            request_label="Google OAuth code exchange",
        )
        payload = self._json_response(response, request_label="Google OAuth code exchange")
        if response.status != 200:
            raise GoogleAuthenticationError(
                "Google OAuth-Codeaustausch ist fehlgeschlagen. "
                f"HTTP-Status: {response.status}. Antwort: {self._short_payload(payload)}"
            )
        return self._build_token_bundle(payload)

    def fetch_user_profile(self, access_token: str) -> GoogleUserProfile:
        response = self._authorized_json_request(
            GOOGLE_USERINFO_URL,
            access_token,
            request_label="Google userinfo",
        )
        payload = self._json_response(response, request_label="Google userinfo")
        if response.status != 200:
            raise GoogleAuthenticationError(
                "Google konnte das Benutzerprofil nicht laden. "
                f"HTTP-Status: {response.status}. Antwort: {self._short_payload(payload)}"
            )

        subject = str(payload.get("sub") or "").strip()
        email = normalize_email(str(payload.get("email") or ""))
        email_verified = bool(payload.get("email_verified"))
        if not subject or not email:
            raise GoogleAuthenticationError(
                "Google hat keine eindeutige Benutzerkennung oder E-Mail geliefert. "
                "Bitte den Login erneut starten."
            )
        if not email_verified:
            raise GoogleAuthenticationError(
                "Google meldet diese E-Mail-Adresse noch nicht als bestaetigt. "
                "Bitte zuerst die Adresse in Google verifizieren."
            )

        return GoogleUserProfile(
            subject=subject,
            email=email,
            email_verified=email_verified,
            name=str(payload.get("name") or "").strip() or None,
            picture_url=str(payload.get("picture") or "").strip() or None,
        )

    def refresh_access_token(self, google_account: "GoogleAccount") -> str:
        current_access_token = self._decrypt_google_secret(
            google_account.access_token,
            "Gespeichertes Google-Access-Token konnte nicht entschluesselt werden. "
            "Bitte Google erneut verbinden.",
        )
        if current_access_token and google_account.expires_at and google_account.expires_at.timestamp() - TOKEN_REFRESH_SKEW_SECONDS >= time.time():
            return current_access_token

        refresh_token = self._decrypt_google_secret(
            google_account.refresh_token,
            "Es ist kein gueltiges Google-Refresh-Token gespeichert. Bitte Google erneut verbinden.",
        )
        if not refresh_token:
            raise GoogleAuthenticationError(
                "Es ist kein gueltiges Google-Refresh-Token gespeichert. Bitte Google erneut verbinden."
            )

        response = self._post_form(
            GOOGLE_TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "refresh_token": refresh_token,
            },
            request_label="Google OAuth token refresh",
        )
        payload = self._json_response(response, request_label="Google OAuth token refresh")
        if response.status != 200:
            raise GoogleAuthenticationError(
                "Google-Refresh-Token konnte nicht erneuert werden. "
                f"HTTP-Status: {response.status}. Antwort: {self._short_payload(payload)}"
            )

        token_bundle = self._build_token_bundle(payload)
        google_account.access_token = encrypt_secret(token_bundle.access_token)
        google_account.refresh_token = encrypt_secret(token_bundle.refresh_token or refresh_token)
        google_account.expires_at = token_bundle.expires_at
        google_account.oauth_scope = token_bundle.scope or google_account.oauth_scope
        google_account.last_error = None
        return token_bundle.access_token

    def send_message(self, google_account: "GoogleAccount", message: EmailMessage) -> None:
        if not google_gmail_send_available(google_account):
            raise GoogleAuthenticationError(
                "Google Mailversand ist fuer dieses Konto noch nicht freigeschaltet. "
                "Bitte den Google-Login erneut mit Gmail-Berechtigung verbinden."
            )

        access_token = self.refresh_access_token(google_account)
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        response = self._authorized_json_request(
            GOOGLE_GMAIL_SEND_URL,
            access_token,
            method="POST",
            payload={"raw": raw_message},
            request_label="Google Gmail messages.send",
        )
        payload = self._json_response(response, request_label="Google Gmail messages.send")
        if response.status not in {200, 202}:
            raise GoogleApiError(
                "Google Gmail API konnte die Nachricht nicht senden. "
                f"HTTP-Status: {response.status}. Antwort: {self._short_payload(payload)}"
            )

    def _post_form(self, url: str, form_data: dict[str, str], *, request_label: str) -> _HttpResponse:
        encoded_payload = parse.urlencode(form_data).encode("utf-8")
        request_object = request.Request(
            url,
            data=encoded_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return self._send(request_object, request_label=request_label)

    def _authorized_json_request(
        self,
        url: str,
        access_token: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        request_label: str,
    ) -> _HttpResponse:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request_object = request.Request(url, data=body, headers=headers, method=method)
        return self._send(request_object, request_label=request_label)

    def _send(self, request_object: request.Request, *, request_label: str) -> _HttpResponse:
        try:
            with request.urlopen(request_object, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
                return _HttpResponse(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except error.HTTPError as exc:
            return _HttpResponse(
                status=exc.code,
                headers=dict(exc.headers.items()),
                body=exc.read(),
            )
        except error.URLError as exc:
            raise GoogleApiError(
                f"{request_label} konnte Google nicht erreichen. Bitte DNS, Firewall und HTTPS-Proxy pruefen: {exc.reason}"
            ) from exc

    def _json_response(self, response: _HttpResponse, *, request_label: str) -> dict[str, Any]:
        if not response.body:
            return {}
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GoogleApiError(
                f"{request_label} lieferte keine gueltige JSON-Antwort. "
                f"HTTP-Status: {response.status}. Antwort-Auszug: {response.body[:200]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise GoogleApiError(
                f"{request_label} lieferte eine unerwartete JSON-Struktur. "
                f"HTTP-Status: {response.status}. Typ: {type(payload).__name__}"
            )
        return payload

    def _build_token_bundle(self, payload: dict[str, Any]) -> GoogleTokenBundle:
        access_token = str(payload.get("access_token") or "").strip()
        refresh_token = str(payload.get("refresh_token") or "").strip() or None
        if not access_token:
            raise GoogleAuthenticationError(
                "Google hat kein Access-Token geliefert. Bitte den Login erneut durchlaufen."
            )
        expires_in_raw = payload.get("expires_in")
        expires_at: datetime | None = None
        try:
            if expires_in_raw is not None:
                expires_at = datetime.fromtimestamp(time.time() + int(expires_in_raw), tz=timezone.utc)
        except (TypeError, ValueError):
            expires_at = None
        return GoogleTokenBundle(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scope=str(payload.get("scope") or "").strip(),
            id_token=str(payload.get("id_token") or "").strip() or None,
        )

    def _short_payload(self, payload: dict[str, Any]) -> str:
        compact = json.dumps(payload, ensure_ascii=False)
        return compact[:300]

    def _decrypt_google_secret(self, value: str | None, fallback_message: str) -> str | None:
        try:
            return decrypt_secret(value)
        except TeslaAuthenticationError as exc:
            raise GoogleAuthenticationError(fallback_message) from exc


def _redirect_uri(settings: Settings) -> str:
    return f"{settings.app_base_url.rstrip('/')}{settings.google_oauth_redirect_path}"
