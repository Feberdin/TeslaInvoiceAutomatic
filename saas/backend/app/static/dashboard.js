/* Purpose: Drive the authenticated dashboard for VINs, Tesla connection variants, recipients, invoice sync and SMTP tests.
Input/Output: Reads the current session from the backend, updates the UI and triggers user actions through the JSON API.
Invariants: Every request relies on the session cookie, users can see both Tesla connection variants side by side, and the preferred live mode stays explicit.
Debug: If actions fail or the wrong Tesla source is selected, inspect `/api/v1/me`, the visible badges and the current preferred live mode first. */

let currentProfile = null;

const MODE_LABELS = {
  auto: "Automatisch",
  fleet_oauth: "Fleet API",
  owner_api: "Inoffizieller Token-Import",
  demo: "Demo-Fallback",
  none: "Noch offen",
};

function isLiveMode(mode) {
  return mode === "fleet_oauth" || mode === "owner_api";
}

function modeLabel(mode) {
  return MODE_LABELS[mode] || "Tesla";
}

function preferredModeExplanation(mode) {
  if (mode === "fleet_oauth") {
    return "Fleet API";
  }
  if (mode === "owner_api") {
    return "in den inoffiziellen Token-Import";
  }
  return "automatisch zuerst in die Fleet API und faellt sonst auf den inoffiziellen Token-Import zurueck";
}

function isConnectedMode(profile, mode) {
  return Array.isArray(profile?.connected_tesla_modes) && profile.connected_tesla_modes.includes(mode);
}

function currentPreferredMode() {
  return document.querySelector('input[name="preferred-live-mode"]:checked')?.value || "auto";
}

function setPreferredMode(mode) {
  const radio = document.querySelector(`input[name="preferred-live-mode"][value="${mode}"]`);
  if (radio) {
    radio.checked = true;
  }
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

  if (!response.ok) {
    throw new Error(extractErrorMessage(payload));
  }

  return payload;
}

function showNotice(message, type = "info") {
  const target = document.getElementById("notice");
  target.className = `notice ${type}`;
  target.textContent = typeof message === "string" ? message : extractErrorMessage(message);
  target.hidden = false;
}

function showTeslaError(message = "") {
  const target = document.getElementById("tesla-error-box");
  target.textContent = message;
  target.hidden = !message;
}

function consumeQueryNotices() {
  const params = new URLSearchParams(window.location.search);
  const teslaStatus = params.get("tesla");
  const teslaError = params.get("tesla_error");
  const importedVehicles = params.get("tesla_imported_vehicles");

  if (teslaStatus === "connected") {
    const importedSuffix = importedVehicles ? ` (${importedVehicles} Fahrzeug(e) importiert)` : "";
    showNotice(`Tesla-Konto wurde erfolgreich verbunden${importedSuffix}.`);
  }
  if (teslaError) {
    showTeslaError(teslaError);
    showNotice(teslaError, "error");
  }

  if (teslaStatus || teslaError || importedVehicles) {
    window.history.replaceState({}, document.title, "/dashboard");
  }
}

function currentRecipients() {
  return document
    .getElementById("recipients")
    .value.split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function currentAccountingTargets() {
  return Array.from(document.querySelectorAll('input[name="accounting-target"]:checked')).map((input) => input.value);
}

function renderAccountingOptions(availableTargets, selectedTargets) {
  const container = document.getElementById("accounting-options");
  container.innerHTML = "";

  for (const target of availableTargets) {
    const wrapper = document.createElement("label");
    wrapper.className = "pill-option";
    wrapper.innerHTML = `
      <input type="checkbox" name="accounting-target" value="${target}" ${selectedTargets.includes(target) ? "checked" : ""} />
      <span>${target}</span>
    `;
    container.appendChild(wrapper);
  }
}

function renderVehicles(vehicles) {
  const container = document.getElementById("vehicle-list");
  container.innerHTML = "";

  if (!vehicles.length) {
    container.innerHTML = '<p class="helper">Noch keine VIN gespeichert.</p>';
    return;
  }

  for (const vehicle of vehicles) {
    const liveVehicle = isLiveMode(vehicle.account_mode);
    const card = document.createElement("div");
    card.className = "list-item list-item-wrap";
    card.innerHTML = `
      <div class="list-copy">
        <strong>${vehicle.nickname}</strong>
        <div class="helper">${vehicle.vin} - ${vehicle.model}</div>
        <div class="tag-row">
          <span class="mini-tag ${liveVehicle ? "tag-live" : "tag-demo"}">${modeLabel(vehicle.account_mode)}</span>
        </div>
      </div>
      <button class="secondary small-button" type="button" data-delete-vehicle="${vehicle.id}">Entfernen</button>
    `;
    container.appendChild(card);
  }

  container.querySelectorAll("[data-delete-vehicle]").forEach((button) => {
    button.addEventListener("click", () => deleteVehicle(Number(button.dataset.deleteVehicle)));
  });
}

function renderInvoices(invoices) {
  const body = document.getElementById("invoice-body");
  body.innerHTML = "";

  if (!invoices.length) {
    body.innerHTML = '<tr><td colspan="7">Noch keine Rechnungen vorhanden. Fuehre zuerst einen Sync aus.</td></tr>';
    return;
  }

  for (const invoice of invoices) {
    const liveInvoice = isLiveMode(invoice.source);
    const amountLabel = invoice.amount > 0 ? `${invoice.amount.toFixed(2)} ${invoice.currency}` : `unbekannt (${invoice.currency})`;
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${invoice.invoice_id}</td>
      <td>${new Date(invoice.charge_started_at).toLocaleString("de-DE")}</td>
      <td>${invoice.vehicle_name}</td>
      <td>${invoice.location}</td>
      <td>${amountLabel}</td>
      <td><span class="mini-tag ${liveInvoice ? "tag-live" : "tag-demo"}">${modeLabel(invoice.source)}</span></td>
      <td><a class="button-link secondary" href="${invoice.pdf_download_url}">PDF laden</a></td>
    `;
    body.appendChild(row);
  }
}

function applyProfile(profile) {
  currentProfile = profile;

  const activeMode = profile.active_sync_mode;
  const liveMode = isLiveMode(activeMode);
  const oauthReady = profile.tesla_oauth_available;
  const ownerImportReady = profile.tesla_owner_import_available;
  const fleetConnected = isConnectedMode(profile, "fleet_oauth");
  const ownerConnected = isConnectedMode(profile, "owner_api");
  const preferredMode = profile.preferred_live_sync_mode || "auto";

  document.getElementById("current-email").textContent = profile.email;
  document.getElementById("metric-vehicles").textContent = String(profile.vehicle_count);
  document.getElementById("metric-invoices").textContent = String(profile.invoice_count);
  document.getElementById("metric-sync").textContent = profile.last_synced_at
    ? new Date(profile.last_synced_at).toLocaleString("de-DE")
    : "noch nie";
  document.getElementById("metric-delivery").textContent = profile.smtp_configured ? "SMTP aktiv" : "Outbox";
  document.getElementById("metric-source").textContent = modeLabel(activeMode);

  document.getElementById("account-delivery-pill").textContent = profile.smtp_configured ? "SMTP aktiv" : "Outbox aktiv";
  document.getElementById("account-tesla-pill").textContent = liveMode
    ? `Aktiv: ${modeLabel(activeMode)}`
    : profile.demo_mode_enabled
      ? "Demo-Fallback aktiv"
      : "Kein Tesla-Zugang";

  document.getElementById("dashboard-mode-chip").textContent = liveMode
    ? `${modeLabel(activeMode)} aktiv`
    : profile.demo_mode_enabled
      ? "Demo-Fallback verfuegbar"
      : "Tesla-Verbindung erforderlich";

  const connectedLabels = profile.connected_tesla_modes.map((mode) => modeLabel(mode));
  document.getElementById("tesla-connection-badge").textContent = connectedLabels.length
    ? `Verbunden: ${connectedLabels.join(" + ")}`
    : oauthReady
      ? "Fleet bereit"
      : ownerImportReady
        ? "Token-Import bereit"
        : "Noch nicht verbunden";

  document.getElementById("tesla-account-email").value = profile.tesla_account_email || "";
  setPreferredMode(preferredMode);

  const modeTitle = activeMode === "fleet_oauth"
    ? "Aktuell echte Rechnungen ueber Fleet API"
    : activeMode === "owner_api"
      ? "Aktuell echte Rechnungen ueber Token-Import"
      : profile.demo_mode_enabled
        ? "Aktuell Demo-Rechnungen als Fallback"
        : "Bitte Tesla verbinden";
  const modeBody = activeMode === "fleet_oauth"
    ? "Der offizielle Tesla-Fleet-Login ist aktiv. Neue Syncs ziehen echte Charging-History und vorhandene Tesla-PDF-Rechnungen fuer deine verbundenen VINs."
    : activeMode === "owner_api"
      ? "Der inoffizielle Token-Import ist aktiv. Neue Syncs laufen ohne Fleet-Billing, koennen aber Tesla-seitig weniger stabil sein."
      : profile.demo_mode_enabled
        ? "Solange kein echter Tesla-Zugang verbunden ist, bleibt der komplette Versand- und Archivfluss ueber Demo-Rechnungen testbar."
        : "Der Demo-Fallback ist deaktiviert. Verbinde jetzt einen Tesla-Zugang und speichere anschliessend deine echten VINs.";
  const nextStep = activeMode === "fleet_oauth" || activeMode === "owner_api"
    ? "Naechster Schritt: Live-Sync ausloesen und eingegangene PDFs im Archiv pruefen"
    : oauthReady
      ? "Naechster Schritt: offiziellen Fleet-Login oder Token-Import verbinden und danach Live-Sync ausloesen"
      : "Naechster Schritt: inoffiziellen Token-Import nutzen oder Fleet-Zugang beim Betreiber aktivieren";

  document.getElementById("tesla-mode-title").textContent = modeTitle;
  document.getElementById("tesla-mode-body").textContent = modeBody;
  document.getElementById("tesla-mode-next-step").textContent = nextStep;
  document.getElementById("dashboard-lead").textContent = liveMode
    ? `Dein Konto ist fuer echte Tesla-Daten vorbereitet. Aktuell laeuft der Live-Weg ueber ${modeLabel(activeMode)}.`
    : "Du testest aktuell den kompletten Nutzer- und Versandfluss fuer dein SaaS-Projekt: Registrierung, VIN-Verwaltung, E-Mail-Versand, PDF-Archiv und zwei Tesla-Verbindungswege.";

  document.getElementById("run-sync").textContent = activeMode === "fleet_oauth"
    ? "Fleet-Sync ausloesen"
    : activeMode === "owner_api"
      ? "Token-Sync ausloesen"
      : "Demo-Sync ausloesen";

  let connectionHelp = "Noch keine Tesla-Verbindung gespeichert.";
  if (fleetConnected && ownerConnected) {
    connectionHelp = `Beide Tesla-Wege sind verbunden. Dein Konto bevorzugt aktuell ${preferredModeExplanation(preferredMode)}.`;
  } else if (fleetConnected) {
    connectionHelp = "Der offizielle Fleet-Login ist verbunden. Du kannst jetzt Live-Syncs fuer echte Rechnungen ausloesen.";
  } else if (ownerConnected) {
    connectionHelp = "Der inoffizielle Token-Import ist verbunden. Du kannst jetzt Live-Syncs ohne Fleet-Billing ausloesen.";
  } else if (oauthReady && ownerImportReady) {
    connectionHelp = "Beide Wege sind fuer diese Installation sichtbar: offizieller Fleet-Login und inoffizieller Token-Import.";
  } else if (oauthReady) {
    connectionHelp = "Fleet ist vorbereitet. Der inoffizielle Token-Import ist auf dieser Installation deaktiviert.";
  } else if (ownerImportReady) {
    connectionHelp = "Fleet ist noch nicht konfiguriert. Fuer echte Rechnungen kannst du den inoffiziellen Token-Import verwenden.";
  }
  document.getElementById("tesla-connection-help").textContent = connectionHelp;

  const oauthButton = document.getElementById("connect-tesla-oauth");
  oauthButton.disabled = !oauthReady;
  oauthButton.textContent = fleetConnected ? "Fleet erneut verbinden" : "Offiziell mit Tesla verbinden";

  const fleetStatusPill = document.getElementById("fleet-status-pill");
  fleetStatusPill.textContent = fleetConnected ? "Verbunden" : oauthReady ? "Bereit" : "Nicht konfiguriert";
  document.getElementById("fleet-help-copy").textContent = fleetConnected
    ? "Dieser offizielle Weg ist bereits verbunden und eignet sich fuer einen spaeteren SaaS-Betrieb mit Endkunden-Login."
    : oauthReady
      ? "Fleet ist konfiguriert. Dieser Weg ist fuer ein spaeteres Produkt am saubersten, kann aber Tesla-seitige Kosten verursachen."
      : "Fleet ist auf dieser Installation noch nicht vollstaendig konfiguriert. Es fehlen Betreiberdaten wie Client ID, Secret oder die richtige Callback-URL.";

  const ownerCard = document.getElementById("owner-card");
  const ownerStatusPill = document.getElementById("owner-status-pill");
  ownerCard.hidden = !ownerImportReady && !ownerConnected;
  ownerStatusPill.textContent = ownerConnected ? "Verbunden" : ownerImportReady ? "Bereit" : "Deaktiviert";
  document.getElementById("owner-help-copy").textContent = ownerConnected
    ? "Dieser inoffizielle Weg ist bereits verbunden und eignet sich gut fuer Self-Hosted-Tests ohne Fleet-Billing."
    : ownerImportReady
      ? "Dieser Weg bleibt fuer technische Nutzer sichtbar. Du brauchst dafuer ein Tesla Refresh-Token oder einen TeslaPy-/tesla_ha-Cache."
      : "Der inoffizielle Token-Import ist auf dieser Installation deaktiviert.";

  for (const radio of document.querySelectorAll('input[name="preferred-live-mode"]')) {
    const value = radio.value;
    if (value === "fleet_oauth") {
      radio.disabled = !oauthReady && !fleetConnected;
    } else if (value === "owner_api") {
      radio.disabled = !ownerImportReady && !ownerConnected;
    } else {
      radio.disabled = false;
    }
  }

  showTeslaError(profile.tesla_last_error || "");
  document.getElementById("recipients").value = profile.email_recipients.join(", ");
  document.getElementById("subject-template").value = profile.subject_template;
  document.getElementById("attach-pdf").checked = profile.attach_pdf;
  renderAccountingOptions(profile.available_accounting_targets, profile.accounting_targets);
  renderVehicles(profile.vehicles);
}

async function refreshDashboard() {
  const profile = await apiRequest("/api/v1/me");
  applyProfile(profile);
  const invoices = await apiRequest("/api/v1/invoices");
  renderInvoices(invoices);
}

function startTeslaOAuth() {
  if (!currentProfile?.tesla_oauth_available || !currentProfile?.tesla_oauth_start_path) {
    const message =
      "Der offizielle Fleet-Login ist fuer diese Installation noch nicht konfiguriert. Bitte zuerst `ENABLE_TESLA_FLEET_OAUTH=true`, Client ID, Client Secret und die korrekte Callback-URL setzen.";
    showTeslaError(message);
    showNotice(message, "error");
    return;
  }
  window.location.href = currentProfile.tesla_oauth_start_path;
}

async function connectTeslaManually() {
  showTeslaError("");
  const payload = await apiRequest("/api/v1/tesla/connect", {
    method: "POST",
    body: JSON.stringify({
      tesla_account_email: document.getElementById("tesla-account-email").value,
      cache_json: document.getElementById("tesla-cache-json").value.trim() || null,
      refresh_token: document.getElementById("tesla-refresh-token").value.trim() || null,
      access_token: document.getElementById("tesla-access-token").value.trim() || null,
    }),
  });

  document.getElementById("tesla-cache-json").value = "";
  document.getElementById("tesla-refresh-token").value = "";
  document.getElementById("tesla-access-token").value = "";
  showNotice(payload.message);
  await refreshDashboard();
}

async function addVehicle() {
  await apiRequest("/api/v1/vehicles", {
    method: "POST",
    body: JSON.stringify({
      vin: document.getElementById("vehicle-vin").value,
      nickname: document.getElementById("vehicle-nickname").value,
    }),
  });
  document.getElementById("vehicle-vin").value = "";
  document.getElementById("vehicle-nickname").value = "";
  showNotice("VIN wurde gespeichert.");
  await refreshDashboard();
}

async function deleteVehicle(vehicleId) {
  await apiRequest(`/api/v1/vehicles/${vehicleId}`, { method: "DELETE" });
  showNotice("VIN wurde entfernt.");
  await refreshDashboard();
}

async function saveSettings() {
  await apiRequest("/api/v1/settings/email", {
    method: "POST",
    body: JSON.stringify({
      recipients: currentRecipients(),
      subject_template: document.getElementById("subject-template").value,
      attach_pdf: document.getElementById("attach-pdf").checked,
      accounting_targets: currentAccountingTargets(),
    }),
  });
  showNotice("Einstellungen wurden gespeichert.");
  await refreshDashboard();
}

async function saveTeslaPreference() {
  const payload = await apiRequest("/api/v1/settings/tesla-mode", {
    method: "POST",
    body: JSON.stringify({
      preferred_live_sync_mode: currentPreferredMode(),
    }),
  });
  showNotice(payload.message);
  await refreshDashboard();
}

async function sendTestEmail() {
  const recipientOverride = document.getElementById("test-email-recipient").value.trim();
  const payload = await apiRequest("/api/v1/email/test", {
    method: "POST",
    body: JSON.stringify({
      recipient_override: recipientOverride || null,
    }),
  });
  showNotice(
    payload.delivery_mode === "smtp"
      ? `Testrechnung wurde per SMTP an ${payload.recipients.join(", ")} versendet.`
      : `Testrechnung wurde fuer ${payload.recipients.join(", ")} im Outbox-Log protokolliert. Fuer echten Versand bitte SMTP setzen.`
  );
}

async function runSync() {
  const payload = await apiRequest("/api/v1/sync/run", {
    method: "POST",
    body: JSON.stringify({
      include_fresh_demo_invoice: !isLiveMode(currentProfile?.active_sync_mode),
    }),
  });

  const deliveryText =
    payload.delivery_mode === "smtp"
      ? " Versand lief per SMTP."
      : payload.delivery_mode === "outbox"
        ? " Versand wurde nur im Outbox-Log protokolliert."
        : "";
  showNotice(
    `${modeLabel(payload.sync_mode)} erfolgreich: ${payload.created_count} neue Rechnung(en), ${payload.skipped_count} bereits bekannt.${deliveryText}`
  );
  await refreshDashboard();
}

async function logout() {
  await apiRequest("/api/v1/auth/logout", { method: "POST" });
  window.location.href = "/auth";
}

document.addEventListener("DOMContentLoaded", async () => {
  consumeQueryNotices();

  document.getElementById("logout-button").addEventListener("click", () =>
    logout().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("connect-tesla-oauth").addEventListener("click", () => startTeslaOAuth());
  document.getElementById("connect-tesla").addEventListener("click", () =>
    connectTeslaManually().catch((error) => {
      showTeslaError(error.message);
      showNotice(error.message, "error");
    })
  );
  document.getElementById("save-tesla-preference").addEventListener("click", () =>
    saveTeslaPreference().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("add-vehicle").addEventListener("click", () =>
    addVehicle().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("save-settings").addEventListener("click", () =>
    saveSettings().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("send-test-email").addEventListener("click", () =>
    sendTestEmail().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("run-sync").addEventListener("click", () =>
    runSync().catch((error) => {
      showTeslaError(error.message);
      showNotice(error.message, "error");
    })
  );

  try {
    await refreshDashboard();
  } catch (error) {
    showNotice(error.message, "error");
  }
});
