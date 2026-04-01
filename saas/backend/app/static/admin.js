/* Purpose: Drive the operator-only Tesla Fleet admin menu, including partner setup and beta debug tools.
Input/Output: Reads `/api/v1/admin/fleet/status` plus `/api/v1/me`, renders diagnostics and triggers explicit admin/debug actions.
Invariants: Private keys never leave the server, all requests stay session-bound and beta debug tooling remains operator-only.
Debug: If Fleet setup or debug tools stop working, compare `/api/v1/admin/fleet/status` and `/api/v1/me` before changing templates. */

let currentAdminStatus = null;
let currentProfile = null;
let currentAdminUsers = [];

const MODE_LABELS = {
  fleet_oauth: "Fleet API",
  owner_api: "Inoffizieller Import",
  demo: "Demo-Fallback",
  none: "Noch offen",
};

function modeLabel(mode) {
  return MODE_LABELS[mode] || "Tesla";
}

function extractErrorMessage(payload) {
  if (!payload) {
    return "Die Anfrage ist fehlgeschlagen.";
  }
  if (typeof payload.detail === "string" && payload.detail.trim()) {
    return payload.detail;
  }
  if (Array.isArray(payload.detail) && payload.detail.length) {
    return payload.detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        const location = Array.isArray(item.loc) ? item.loc.join(" -> ") : "Eingabe";
        return `${location}: ${item.msg || "ungueltiger Wert"}`;
      })
      .join(" | ");
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

function humanizeSyncInterval(seconds) {
  if (!seconds || Number.isNaN(seconds)) {
    return "-";
  }
  if (seconds % 3600 === 0) {
    return `${seconds / 3600} Std.`;
  }
  if (seconds % 60 === 0) {
    return `${seconds / 60} Min.`;
  }
  return `${seconds} Sek.`;
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
  document.getElementById("admin-sync-interval").textContent = humanizeSyncInterval(status.sync_interval_seconds);
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

function renderVehicles(vehicles) {
  const container = document.getElementById("debug-vehicle-list");
  container.innerHTML = "";

  if (!vehicles.length) {
    container.innerHTML = '<p class="helper">Noch keine VIN registriert.</p>';
    return;
  }

  for (const vehicle of vehicles) {
    const card = document.createElement("div");
    card.className = "list-item list-item-wrap";
    card.innerHTML = `
      <div class="list-copy">
        <strong>${vehicle.nickname}</strong>
        <div class="helper">${vehicle.vin} - ${vehicle.model}</div>
        <div class="tag-row">
          <span class="mini-tag ${vehicle.account_mode === "fleet_oauth" ? "tag-live" : "tag-demo"}">${modeLabel(vehicle.account_mode)}</span>
        </div>
      </div>
      <button class="secondary small-button" type="button" data-delete-vehicle="${vehicle.id}">Entfernen</button>
    `;
    container.appendChild(card);
  }

  container.querySelectorAll("[data-delete-vehicle]").forEach((button) => {
    button.addEventListener("click", () =>
      deleteVehicle(Number(button.dataset.deleteVehicle)).catch((error) => showNotice(error.message, "error"))
    );
  });
}

function renderProfile(profile) {
  currentProfile = profile;
  renderVehicles(profile.vehicles);

  const ownerImportEnabled = Boolean(profile.tesla_owner_import_available);
  document.getElementById("admin-owner-import-pill").textContent = ownerImportEnabled
    ? "Token-Import bereit"
    : "Token-Import deaktiviert";
  document.getElementById("debug-owner-connect-button").disabled = !ownerImportEnabled;
  document.getElementById("debug-owner-import-help").textContent = ownerImportEnabled
    ? "Dieser Import bleibt fuer Self-Hosted-Debug und Vergleichstests verfuegbar, falls du Beta-Faelle ohne Fleet-Billing nachvollziehen willst."
    : "Der inoffizielle Token-Import ist auf dieser Installation deaktiviert. Setze dafuer `ENABLE_TESLA_OWNER_IMPORT=true`.";

  const ownerEmailInput = document.getElementById("debug-owner-email");
  if (!ownerEmailInput.value.trim()) {
    ownerEmailInput.value = profile.tesla_connection_mode === "owner_api" && profile.tesla_account_email
      ? profile.tesla_account_email
      : profile.email;
  }
}

function renderRegisteredUsers(users) {
  currentAdminUsers = users;
  const container = document.getElementById("admin-user-list");
  const pill = document.getElementById("admin-user-count-pill");
  container.innerHTML = "";
  pill.textContent = `${users.length} Konto/Konten`;

  if (!users.length) {
    container.innerHTML = '<p class="helper">Noch keine Registrierungen vorhanden.</p>';
    return;
  }

  for (const user of users) {
    const card = document.createElement("div");
    card.className = "list-item list-item-wrap";
    const vehicleTags = user.vehicles.length
      ? user.vehicles
          .map((vehicle) => {
            const tagClass = vehicle.account_mode === "fleet_oauth" ? "tag-live" : "tag-demo";
            return `
              <div class="admin-vehicle-row">
                <strong>${vehicle.nickname}</strong>
                <span class="helper">${vehicle.vin}</span>
                <span class="mini-tag ${tagClass}">${modeLabel(vehicle.account_mode)}</span>
              </div>
            `;
          })
          .join("")
      : '<p class="helper">Noch kein Fahrzeug registriert.</p>';

    card.innerHTML = `
      <div class="list-copy">
        <strong>${user.email}</strong>
        <div class="helper">
          Registriert: ${new Date(user.created_at).toLocaleString("de-DE")} |
          Aktiv: ${modeLabel(user.active_sync_mode)} |
          Letzter Sync: ${user.last_synced_at ? new Date(user.last_synced_at).toLocaleString("de-DE") : "noch nie"}
        </div>
        <div class="admin-user-vehicles">${vehicleTags}</div>
      </div>
    `;
    container.appendChild(card);
  }
}

async function refreshStatus() {
  const status = await apiRequest("/api/v1/admin/fleet/status");
  renderStatus(status);
}

async function refreshProfile() {
  const profile = await apiRequest("/api/v1/me");
  renderProfile(profile);
}

async function refreshRegisteredUsers() {
  const users = await apiRequest("/api/v1/admin/users");
  renderRegisteredUsers(users);
}

async function refreshAdminPage() {
  const [status, profile, users] = await Promise.all([
    apiRequest("/api/v1/admin/fleet/status"),
    apiRequest("/api/v1/me"),
    apiRequest("/api/v1/admin/users"),
  ]);
  renderStatus(status);
  renderProfile(profile);
  renderRegisteredUsers(users);
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

async function sendDebugTestEmail() {
  const recipientOverride = document.getElementById("debug-test-email-override").value.trim() || null;
  const payload = await apiRequest("/api/v1/email/test", {
    method: "POST",
    body: JSON.stringify({ recipient_override: recipientOverride }),
  });
  const recipients = Array.isArray(payload.recipients) ? payload.recipients.join(", ") : "";
  const ccRecipients = Array.isArray(payload.cc_recipients) ? payload.cc_recipients.join(", ") : "";
  const fromEmail = payload.from_email || "unbekannt";
  showNotice(
    `Testmail verarbeitet. Modus: ${payload.delivery_mode}. Von: ${fromEmail}. Empfaenger: ${recipients || "keine"}${ccRecipients ? ` | CC: ${ccRecipients}` : ""}.`
  );
}

async function addVehicle() {
  const vin = document.getElementById("debug-vin").value.trim();
  const nickname = document.getElementById("debug-vin-nickname").value.trim();
  const payload = await apiRequest("/api/v1/vehicles", {
    method: "POST",
    body: JSON.stringify({ vin, nickname }),
  });
  showNotice(`VIN ${payload.vin} wurde gespeichert.`);
  document.getElementById("debug-vin").value = "";
  document.getElementById("debug-vin-nickname").value = "";
  await Promise.all([refreshProfile(), refreshRegisteredUsers()]);
}

async function deleteVehicle(vehicleId) {
  const payload = await apiRequest(`/api/v1/vehicles/${vehicleId}`, { method: "DELETE" });
  showNotice(payload.message);
  await Promise.all([refreshProfile(), refreshRegisteredUsers()]);
}

async function connectOwnerImport() {
  const payload = await apiRequest("/api/v1/tesla/connect", {
    method: "POST",
    body: JSON.stringify({
      tesla_account_email: document.getElementById("debug-owner-email").value.trim(),
      cache_json: document.getElementById("debug-owner-cache-json").value.trim() || null,
      refresh_token: document.getElementById("debug-owner-refresh-token").value.trim() || null,
      access_token: document.getElementById("debug-owner-access-token").value.trim() || null,
    }),
  });
  showNotice(payload.message);
  document.getElementById("debug-owner-cache-json").value = "";
  document.getElementById("debug-owner-refresh-token").value = "";
  document.getElementById("debug-owner-access-token").value = "";
  await Promise.all([refreshProfile(), refreshRegisteredUsers()]);
}

async function purgeDemoInvoices() {
  const confirmed = window.confirm(
    "Alle gespeicherten Demo-Rechnungen und Demo-PDFs werden geloescht. Live-Rechnungen bleiben erhalten. Fortfahren?"
  );
  if (!confirmed) {
    return;
  }

  const payload = await apiRequest("/api/v1/admin/demo/purge", {
    method: "POST",
    body: JSON.stringify({}),
  });
  showNotice(payload.message);
  await Promise.all([refreshProfile(), refreshRegisteredUsers()]);
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
  document.getElementById("debug-send-test-email-button").addEventListener("click", () =>
    sendDebugTestEmail().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("debug-add-vehicle-button").addEventListener("click", () =>
    addVehicle().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("debug-owner-connect-button").addEventListener("click", () =>
    connectOwnerImport().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("debug-purge-demo-button").addEventListener("click", () =>
    purgeDemoInvoices().catch((error) => showNotice(error.message, "error"))
  );

  try {
    await refreshAdminPage();
  } catch (error) {
    showNotice(error.message, "error");
  }
});
