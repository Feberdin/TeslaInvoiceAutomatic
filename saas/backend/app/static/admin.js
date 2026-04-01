/* Purpose: Drive the operator-only Tesla Fleet admin menu for key generation, partner registration and verification.
Input/Output: Fetches `/api/v1/admin/fleet/*` endpoints, renders diagnostics and triggers explicit admin actions.
Invariants: This page never exposes private-key contents, and all requests rely on the existing session cookie plus server-side admin checks.
Debug: If Tesla partner setup still fails, inspect the rendered HTTP status, the public-key URL and the latest register/verify messages first. */

let currentAdminStatus = null;

function extractErrorMessage(payload) {
  if (!payload) {
    return "Die Anfrage ist fehlgeschlagen.";
  }
  if (typeof payload.detail === "string" && payload.detail.trim()) {
    return payload.detail;
  }
  if (typeof payload.message === "string" && payload.message.trim()) {
    return payload.message;
  }
  return "Die Anfrage ist fehlgeschlagen.";
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : null;

  if (response.status === 401) {
    window.location.href = "/auth";
    throw new Error("Deine Sitzung ist abgelaufen.");
  }
  if (response.status === 403) {
    window.location.href = "/dashboard";
    throw new Error("Dieses Menue ist nur fuer Betreiber freigegeben.");
  }
  if (!response.ok) {
    throw new Error(extractErrorMessage(payload));
  }
  return payload;
}

function showNotice(message, type = "info") {
  const target = document.getElementById("admin-notice");
  target.className = `notice ${type}`;
  target.textContent = message;
  target.hidden = !message;
}

function formatDate(value) {
  return value ? new Date(value).toLocaleString("de-DE") : "noch nie";
}

function labelFromStatus(status) {
  switch (status) {
    case "success":
      return "erfolgreich";
    case "registered":
      return "registriert";
    case "missing":
      return "nicht gefunden";
    case "generated":
      return "erzeugt";
    case "stale":
      return "erneut noetig";
    case "error":
      return "Fehler";
    case "not_started":
    default:
      return "noch offen";
  }
}

function renderStatus(status) {
  currentAdminStatus = status;

  document.getElementById("admin-app-domain").textContent = status.app_domain;
  document.getElementById("admin-fleet-base").textContent = status.fleet_api_base_url;
  document.getElementById("admin-key-status").textContent = status.public_key_present ? "vorhanden" : "fehlt";
  document.getElementById("admin-verify-status").textContent = labelFromStatus(status.last_verify_status);
  document.getElementById("admin-public-key-url").textContent = status.public_key_url;
  document.getElementById("admin-callback-url").textContent = status.callback_url;
  document.getElementById("admin-public-key-fingerprint").textContent = status.public_key_fingerprint || "noch keiner";
  document.getElementById("admin-key-generated-at").textContent = formatDate(status.key_generated_at);
  document.getElementById("admin-public-key-preview").textContent = status.public_key_pem || "Noch kein Public Key erzeugt.";
  document.getElementById("admin-last-register-status").textContent = labelFromStatus(status.last_register_status);
  document.getElementById("admin-last-register-message").textContent =
    status.last_register_message || "Noch kein Register-Aufruf ausgefuehrt.";
  document.getElementById("admin-last-verify-status").textContent = labelFromStatus(status.last_verify_status);
  document.getElementById("admin-last-verify-message").textContent =
    status.last_verify_message || "Noch keine Tesla-Pruefung ausgefuehrt.";
  document.getElementById("admin-partner-scope").textContent = status.partner_token_scope;
  document.getElementById("admin-last-http-status").textContent =
    String(status.last_verify_http_status || status.last_register_http_status || "-");

  const publicKeyLink = document.getElementById("public-key-link");
  publicKeyLink.href = status.public_key_url;

  document.getElementById("admin-oauth-pill").textContent = status.oauth_ready ? "Fleet OAuth bereit" : "Fleet OAuth unvollstaendig";
  document.getElementById("admin-key-pill").textContent = status.public_key_present ? "Public Key vorhanden" : "Public Key fehlt";
  document.getElementById("admin-register-pill").textContent = status.register_ready
    ? "Register-Flow bereit"
    : "Vorbereitung noetig";

  document.getElementById("verify-partner-button").disabled = !status.oauth_ready;
  document.getElementById("register-partner-button").disabled = !status.register_ready;
  document.getElementById("generate-key-button").textContent = status.public_key_present
    ? "Public Key neu erzeugen"
    : "Public Key erzeugen";
}

async function refreshStatus() {
  const status = await apiRequest("/api/v1/admin/fleet/status");
  renderStatus(status);
}

async function generateKeyPair() {
  const force = currentAdminStatus?.public_key_present
    ? window.confirm(
        "Es existiert bereits ein Fleet-Key. Wenn du neu erzeugst, solltest du Tesla danach erneut registrieren. Fortfahren?"
      )
    : false;

  if (currentAdminStatus?.public_key_present && !force) {
    return;
  }

  const payload = await apiRequest("/api/v1/admin/fleet/keys/generate", {
    method: "POST",
    body: JSON.stringify({ force }),
  });
  showNotice(payload.message);
  await refreshStatus();
}

async function verifyPartnerRegistration() {
  const payload = await apiRequest("/api/v1/admin/fleet/verify", { method: "POST" });
  showNotice(payload.message);
  await refreshStatus();
}

async function registerPartnerApplication() {
  const payload = await apiRequest("/api/v1/admin/fleet/register", { method: "POST" });
  showNotice(payload.message);
  await refreshStatus();
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("generate-key-button").addEventListener("click", () =>
    generateKeyPair().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("verify-partner-button").addEventListener("click", () =>
    verifyPartnerRegistration().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("register-partner-button").addEventListener("click", () =>
    registerPartnerApplication().catch((error) => showNotice(error.message, "error"))
  );

  try {
    await refreshStatus();
  } catch (error) {
    showNotice(error.message, "error");
  }
});
