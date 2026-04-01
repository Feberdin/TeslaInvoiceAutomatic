/* Purpose: Drive the authenticated dashboard for the Fleet beta flow, delivery settings and invoice archive.
Input/Output: Reads `/api/v1/me` plus `/api/v1/invoices`, renders the current account state and triggers JSON API actions.
Invariants: The dashboard stays session-bound, only shows registered VINs, and keeps manual debug tools inside the operator menu.
Debug: If the page looks inconsistent after a backend change, inspect `/api/v1/me`, `/api/v1/invoices`, query notices and the visible Fleet status badges first. */

let currentProfile = null;

const MODE_LABELS = {
  fleet_oauth: "Fleet API",
  owner_api: "Inoffizieller Import",
  demo: "Demo-Fallback",
  none: "Noch offen",
};

function isLiveMode(mode) {
  return mode === "fleet_oauth" || mode === "owner_api";
}

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

function renderAccountingOptions(availableTargets, selectedTargets, implementedTargets) {
  const container = document.getElementById("accounting-options");
  container.innerHTML = "";
  const implemented = new Set(implementedTargets);

  for (const target of availableTargets) {
    const isImplemented = implemented.has(target);
    const wrapper = document.createElement("label");
    wrapper.className = `pill-option ${isImplemented ? "pill-option-live" : "pill-option-placeholder"}`;
    wrapper.innerHTML = `
      <input type="checkbox" name="accounting-target" value="${target}" ${selectedTargets.includes(target) ? "checked" : ""} />
      <span class="pill-option-copy">
        <strong>${target}</strong>
        <small>${isImplemented ? "Bereits aktiv" : "Noch nicht implementiert"}</small>
      </span>
    `;
    container.appendChild(wrapper);
  }
}

function renderVehicles(vehicles) {
  const container = document.getElementById("vehicle-list");
  container.innerHTML = "";

  if (!vehicles.length) {
    container.innerHTML = '<p class="helper">Noch keine VIN registriert. Verbinde zuerst Tesla oder nutze das Admin-Menue fuer Debug-VINs.</p>';
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
    `;
    container.appendChild(card);
  }
}

function renderInvoices(invoices) {
  const body = document.getElementById("invoice-body");
  body.innerHTML = "";

  if (!invoices.length) {
    body.innerHTML = '<tr><td colspan="5">Noch keine Rechnungen vorhanden. Fuehre zuerst einen Sync aus.</td></tr>';
    return;
  }

  for (const invoice of invoices) {
    const amountLabel = invoice.amount > 0 ? `${invoice.amount.toFixed(2)} ${invoice.currency}` : `unbekannt (${invoice.currency})`;
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${new Date(invoice.charge_started_at).toLocaleString("de-DE")}</td>
      <td>${invoice.vehicle_name}</td>
      <td>${invoice.location}</td>
      <td>${amountLabel}</td>
      <td><a class="button-link secondary" href="${invoice.pdf_download_url}">PDF laden</a></td>
    `;
    body.appendChild(row);
  }
}

function applyFleetTexts(profile) {
  const activeMode = profile.active_sync_mode;
  const fleetConnected = activeMode === "fleet_oauth";
  const ownerConnected = activeMode === "owner_api";
  const demoActive = activeMode === "demo";

  const accountTeslaPill = document.getElementById("account-tesla-pill");
  const dashboardModeChip = document.getElementById("dashboard-mode-chip");
  const teslaModeTitle = document.getElementById("tesla-mode-title");
  const teslaModeBody = document.getElementById("tesla-mode-body");
  const nextStep = document.getElementById("tesla-mode-next-step");
  const connectionBadge = document.getElementById("tesla-connection-badge");
  const fleetStatusPill = document.getElementById("fleet-status-pill");
  const fleetHelpCopy = document.getElementById("fleet-help-copy");
  const connectionHelp = document.getElementById("tesla-connection-help");
  const connectButton = document.getElementById("connect-tesla-oauth");
  const syncButton = document.getElementById("run-sync");

  if (fleetConnected) {
    accountTeslaPill.textContent = "Aktiv: Fleet API";
    dashboardModeChip.textContent = "Fleet API aktiv";
    dashboardModeChip.className = "status-chip ok";
    teslaModeTitle.textContent = "Aktuell echte Rechnungen ueber Fleet API";
    teslaModeBody.textContent =
      "Der offizielle Tesla-Fleet-Login ist aktiv. Neue Syncs ziehen echte Charging-History und vorhandene Tesla-PDF-Rechnungen fuer deine verbundenen VINs.";
    nextStep.textContent = "Naechster Schritt: Live-Sync ausloesen und eingegangene PDFs im Archiv pruefen";
    connectionBadge.textContent = "Verbunden: Fleet API";
    fleetStatusPill.textContent = "Verbunden";
    fleetHelpCopy.textContent =
      "Dieser offizielle Weg ist bereits verbunden und eignet sich fuer den Beta-Test sowie fuer spaeteren SaaS-Betrieb mit Endkunden-Login.";
    connectionHelp.textContent =
      "Der Beta-Test nutzt den offiziellen Tesla-Fleet-Login. Zusaetzliche Debug-Werkzeuge wie der inoffizielle Token-Import liegen bewusst nur im Admin-Menue.";
    connectButton.textContent = "Fleet erneut verbinden";
    connectButton.disabled = !profile.tesla_oauth_available;
    syncButton.textContent = "Fleet-Sync ausloesen";
    return;
  }

  if (ownerConnected) {
    accountTeslaPill.textContent = "Aktiv: Inoffizieller Import";
    dashboardModeChip.textContent = "Inoffizieller Import aktiv";
    dashboardModeChip.className = "status-chip ok";
    teslaModeTitle.textContent = "Aktuell echte Rechnungen ueber inoffiziellen Import";
    teslaModeBody.textContent =
      "Ein inoffizieller Tesla-Token-Import ist verbunden. Fuer den Beta-Test kannst du damit ebenfalls echte Rechnungen laden, auch wenn der Fleet-Flow gerade nicht genutzt wird.";
    nextStep.textContent = "Naechster Schritt: Live-Sync ausloesen und danach das PDF-Archiv pruefen";
    connectionBadge.textContent = "Live-Zugang aktiv";
    fleetStatusPill.textContent = profile.tesla_oauth_available ? "Fleet verfuegbar" : "Fleet nicht verfuegbar";
    fleetHelpCopy.textContent =
      "Der Fleet-Login ist auf dieser Installation verfuegbar, aktuell aber nicht der aktive Live-Weg. Fuer Owner-Debug-Werkzeuge nutze das Admin-Menue.";
    connectionHelp.textContent =
      "Der Beta-Test bevorzugt Fleet API, kann aber bei Bedarf ueber das Admin-Menue auch mit dem inoffiziellen Import debuggt werden.";
    connectButton.textContent = "Offiziell mit Tesla verbinden";
    connectButton.disabled = !profile.tesla_oauth_available;
    syncButton.textContent = "Live-Sync ausloesen";
    return;
  }

  if (demoActive) {
    accountTeslaPill.textContent = "Demo-Fallback aktiv";
    dashboardModeChip.textContent = "Demo-Fallback verfuegbar";
    dashboardModeChip.className = "status-chip muted";
    teslaModeTitle.textContent = "Aktuell Demo-Rechnungen als Fallback";
    teslaModeBody.textContent =
      "Noch ist kein echter Live-Weg aktiv. Solange `DEMO_MODE=true` gesetzt ist, kannst du den Versand- und Archivfluss weiterhin mit Demo-Rechnungen pruefen.";
    nextStep.textContent = "Naechster Schritt: Offiziellen Fleet-Login verbinden und danach Live-Sync ausloesen";
    connectionBadge.textContent = "Noch nicht verbunden";
    fleetStatusPill.textContent = profile.tesla_oauth_available ? "Fleet bereit" : "Fleet fehlt";
    fleetHelpCopy.textContent =
      "Fuer spaeteren Kundeneinsatz gedacht. Dieser Weg ist der offizielle Tesla-Flow, benoetigt aber Fleet-API-Konfiguration und kann Tesla-seitige Kosten verursachen.";
    connectionHelp.textContent =
      "Der Beta-Test nutzt den offiziellen Tesla-Fleet-Login. Zusaetzliche Debug-Werkzeuge wie der inoffizielle Token-Import liegen bewusst nur im Admin-Menue.";
    connectButton.textContent = "Offiziell mit Tesla verbinden";
    connectButton.disabled = !profile.tesla_oauth_available;
    syncButton.textContent = "Demo-Sync ausloesen";
    return;
  }

  accountTeslaPill.textContent = "Tesla noch offen";
  dashboardModeChip.textContent = "Tesla noch nicht verbunden";
  dashboardModeChip.className = "status-chip muted";
  teslaModeTitle.textContent = "Bitte Tesla verbinden";
  teslaModeBody.textContent =
    "Der offizielle Fleet-Login ist der empfohlene Beta-Weg. Ohne verbundenes Tesla-Konto bleibt nur der lokale Demo-Fallback oder das Admin-Debug-Menue.";
  nextStep.textContent = "Als naechster Schritt: Tesla-Zugang verbinden und Live-Sync ausloesen";
  connectionBadge.textContent = "Noch nicht verbunden";
  fleetStatusPill.textContent = profile.tesla_oauth_available ? "Fleet bereit" : "Fleet nicht konfiguriert";
  fleetHelpCopy.textContent =
    "Fuer spaeteren Kundeneinsatz gedacht. Dieser Weg ist der offizielle Tesla-Flow, benoetigt aber Fleet-API-Konfiguration und kann Tesla-seitige Kosten verursachen.";
  connectionHelp.textContent =
    "Der Beta-Test nutzt den offiziellen Tesla-Fleet-Login. Zusaetzliche Debug-Werkzeuge wie der inoffizielle Token-Import liegen bewusst nur im Admin-Menue.";
  connectButton.textContent = "Offiziell mit Tesla verbinden";
  connectButton.disabled = !profile.tesla_oauth_available;
  syncButton.textContent = "Sync ausloesen";
}

function applyProfile(profile) {
  currentProfile = profile;

  document.getElementById("current-email").textContent = profile.email;
  document.getElementById("metric-vehicles").textContent = String(profile.vehicle_count);
  document.getElementById("metric-invoices").textContent = String(profile.invoice_count);
  document.getElementById("metric-sync").textContent = profile.last_synced_at
    ? new Date(profile.last_synced_at).toLocaleString("de-DE")
    : "noch nie";
  document.getElementById("metric-source").textContent = modeLabel(profile.active_sync_mode);
  document.getElementById("metric-delivery").textContent = profile.smtp_configured ? "SMTP aktiv" : "Outbox aktiv";

  document.getElementById("recipients").value = profile.email_recipients.join(", ");
  document.getElementById("subject-template").value = profile.subject_template;
  document.getElementById("attach-pdf").checked = profile.attach_pdf;
  document.getElementById("employee-sender-email").value = profile.employee_sender_email || "";

  document.getElementById("account-delivery-pill").textContent = profile.smtp_configured ? "SMTP aktiv" : "Outbox aktiv";
  renderAccountingOptions(
    profile.available_accounting_targets,
    profile.accounting_targets,
    profile.implemented_accounting_targets || []
  );
  renderVehicles(profile.vehicles);
  applyFleetTexts(profile);
  showTeslaError(profile.tesla_last_error || "");

  const adminEntry = document.getElementById("admin-entry");
  adminEntry.hidden = !profile.is_admin;
  if (profile.is_admin && profile.admin_path) {
    document.getElementById("admin-link").href = profile.admin_path;
  }
}

async function refreshDashboard() {
  const [profile, invoices] = await Promise.all([apiRequest("/api/v1/me"), apiRequest("/api/v1/invoices")]);
  applyProfile(profile);
  renderInvoices(invoices);
}

async function logout() {
  await apiRequest("/api/v1/auth/logout", { method: "POST", body: JSON.stringify({}) });
  window.location.href = "/auth";
}

async function saveSettings() {
  const payload = {
    recipients: currentRecipients(),
    subject_template: document.getElementById("subject-template").value.trim(),
    attach_pdf: document.getElementById("attach-pdf").checked,
    accounting_targets: currentAccountingTargets(),
    employee_sender_email: document.getElementById("employee-sender-email").value.trim() || null,
  };
  const result = await apiRequest("/api/v1/settings/email", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  showNotice(result.message);
  await refreshDashboard();
}

async function sendTestEmail() {
  const result = await apiRequest("/api/v1/email/test", {
    method: "POST",
    body: JSON.stringify({ recipient_override: null }),
  });
  const ccRecipients = (result.cc_recipients || []).join(", ");
  const fromEmail = result.from_email || "unbekannt";
  showNotice(
    `Testmail wurde verarbeitet. Modus: ${result.delivery_mode}. Von: ${fromEmail}. Empfaenger: ${(result.recipients || []).join(", ") || "keine"}${ccRecipients ? ` | CC: ${ccRecipients}` : ""}.`
  );
}

function connectTeslaOauth() {
  if (!currentProfile?.tesla_oauth_available || !currentProfile?.tesla_oauth_start_path) {
    showNotice(
      "Fleet OAuth ist auf dieser Installation noch nicht vollstaendig konfiguriert. Bitte zuerst die Betreiber-Einstellungen pruefen.",
      "error"
    );
    return;
  }
  window.location.href = currentProfile.tesla_oauth_start_path;
}

async function runSync() {
  const includeFreshDemoInvoice = !currentProfile?.tesla_connected && Boolean(currentProfile?.demo_mode_enabled);
  const result = await apiRequest("/api/v1/sync/run", {
    method: "POST",
    body: JSON.stringify({ include_fresh_demo_invoice: includeFreshDemoInvoice }),
  });
  showNotice(
    `Sync erfolgreich. Neu: ${result.created_count}, uebersprungen: ${result.skipped_count}, Versand: ${result.delivery_mode}.`
  );
  await refreshDashboard();
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("logout-button").addEventListener("click", () =>
    logout().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("save-settings").addEventListener("click", () =>
    saveSettings().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("send-test-email").addEventListener("click", () =>
    sendTestEmail().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("connect-tesla-oauth").addEventListener("click", connectTeslaOauth);
  document.getElementById("run-sync").addEventListener("click", () =>
    runSync().catch((error) => showNotice(error.message, "error"))
  );

  consumeQueryNotices();

  try {
    await refreshDashboard();
  } catch (error) {
    showNotice(error.message, "error");
  }
});
