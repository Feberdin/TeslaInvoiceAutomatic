/* Purpose: Drive the authenticated dashboard for VINs, Tesla OAuth, recipients, invoice sync and SMTP tests.
Input/Output: Reads the current session from the backend, updates the UI and triggers user actions through the JSON API.
Invariants: Every request relies on the session cookie, so the user never has to type their SaaS e-mail repeatedly.
Debug: If actions fail, inspect the API response body, the visible Tesla mode badges and the dashboard query parameters before changing backend logic. */

let currentProfile = null;

function isLiveMode(mode) {
  return mode === "fleet_oauth" || mode === "owner_api";
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
    const modeLabel = liveVehicle ? "Live Tesla" : "Demo";
    const card = document.createElement("div");
    card.className = "list-item list-item-wrap";
    card.innerHTML = `
      <div class="list-copy">
        <strong>${vehicle.nickname}</strong>
        <div class="helper">${vehicle.vin} - ${vehicle.model}</div>
        <div class="tag-row">
          <span class="mini-tag ${liveVehicle ? "tag-live" : "tag-demo"}">${modeLabel}</span>
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
    const sourceLabel = liveInvoice ? "Live Tesla" : "Demo";
    const amountLabel = invoice.amount > 0 ? `${invoice.amount.toFixed(2)} ${invoice.currency}` : `unbekannt (${invoice.currency})`;
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${invoice.invoice_id}</td>
      <td>${new Date(invoice.charge_started_at).toLocaleString("de-DE")}</td>
      <td>${invoice.vehicle_name}</td>
      <td>${invoice.location}</td>
      <td>${amountLabel}</td>
      <td><span class="mini-tag ${liveInvoice ? "tag-live" : "tag-demo"}">${sourceLabel}</span></td>
      <td><a class="button-link secondary" href="${invoice.pdf_download_url}">PDF laden</a></td>
    `;
    body.appendChild(row);
  }
}

function applyProfile(profile) {
  currentProfile = profile;
  const liveMode = isLiveMode(profile.active_sync_mode);
  const oauthReady = profile.tesla_oauth_available;

  document.getElementById("current-email").textContent = profile.email;
  document.getElementById("metric-vehicles").textContent = String(profile.vehicle_count);
  document.getElementById("metric-invoices").textContent = String(profile.invoice_count);
  document.getElementById("metric-sync").textContent = profile.last_synced_at
    ? new Date(profile.last_synced_at).toLocaleString("de-DE")
    : "noch nie";

  const deliveryText = profile.smtp_configured ? "SMTP aktiv" : "Outbox";
  const syncModeLabel = liveMode ? "Live Tesla" : profile.active_sync_mode === "demo" ? "Demo" : "Noch offen";

  document.getElementById("metric-delivery").textContent = deliveryText;
  document.getElementById("metric-source").textContent = syncModeLabel;
  document.getElementById("account-delivery-pill").textContent = profile.smtp_configured ? "SMTP aktiv" : "Outbox aktiv";
  document.getElementById("account-tesla-pill").textContent = liveMode
    ? "Live Tesla aktiv"
    : profile.demo_mode_enabled
      ? "Demo-Fallback aktiv"
      : "Tesla benoetigt";

  document.getElementById("dashboard-mode-chip").textContent = liveMode
    ? "Live-Tesla verbunden"
    : profile.demo_mode_enabled
      ? "Demo-Fallback verfuegbar"
      : "Tesla-Verbindung erforderlich";

  document.getElementById("tesla-connection-badge").textContent = profile.tesla_connected
    ? `Verbunden: ${profile.tesla_account_email || "Tesla Konto"}`
    : oauthReady
      ? "OAuth bereit"
      : "OAuth noch nicht konfiguriert";

  document.getElementById("tesla-account-email").value = profile.tesla_account_email || "";

  const modeTitle = liveMode
    ? "Aktuell echte Tesla-Rechnungen"
    : profile.demo_mode_enabled
      ? "Aktuell Demo-Rechnungen als Fallback"
      : "Bitte Tesla verbinden";
  const modeBody = liveMode
    ? "Neue Syncs rufen jetzt echte Tesla-Charging-History und vorhandene PDF-Rechnungen fuer deine gespeicherten VINs ab."
    : profile.demo_mode_enabled
      ? "Solange kein echter Tesla-Zugang verbunden ist, kannst du weiterhin den kompletten Versand- und Archivfluss mit Demo-Rechnungen testen."
      : "Der Demo-Fallback ist deaktiviert. Verbinde jetzt einen Tesla-Zugang und speichere anschliessend deine echten VINs.";
  const nextStep = liveMode
    ? "Naechster Schritt: Live-Sync ausloesen und eingegangene PDFs im Archiv pruefen"
    : oauthReady
      ? "Naechster Schritt: Mit Tesla verbinden, VIN pruefen und Live-Sync ausloesen"
      : "Naechster Schritt: Betreiber-Konfiguration fuer Tesla OAuth vervollstaendigen";

  document.getElementById("tesla-mode-title").textContent = modeTitle;
  document.getElementById("tesla-mode-body").textContent = modeBody;
  document.getElementById("tesla-mode-next-step").textContent = nextStep;
  document.getElementById("dashboard-lead").textContent = liveMode
    ? "Dein Konto ist fuer echte Tesla-Daten vorbereitet: VINs, Mailversand, PDF-Archiv und Live-Sync laufen ueber denselben SaaS-Fluss."
    : "Du testest aktuell den kompletten Nutzer- und Versandfluss fuer dein SaaS-Projekt: Registrierung, VIN-Verwaltung, E-Mail-Versand, PDF-Archiv und Buchhaltungsziele.";

  document.getElementById("run-sync").textContent = liveMode ? "Tesla-Sync ausloesen" : "Demo-Sync ausloesen";

  document.getElementById("tesla-connection-help").textContent = liveMode
    ? "Dein Tesla-Konto ist ueber einen Live-Zugang verbunden. Du kannst jetzt neue VINs speichern oder direkt einen Tesla-Sync ausloesen."
    : oauthReady
      ? "Kunden koennen sich jetzt per offiziellem Tesla-Login verbinden. Der manuelle Token-Import bleibt nur als Experten-Fallback sichtbar."
      : "Fuer den offiziellen Tesla-Login fehlen noch Betreiber-Daten wie `TESLA_CLIENT_ID`, `TESLA_CLIENT_SECRET` und die korrekte Fleet-API-Region.";

  const oauthButton = document.getElementById("connect-tesla-oauth");
  oauthButton.disabled = !oauthReady;
  oauthButton.textContent = oauthReady ? "Mit Tesla verbinden" : "Tesla OAuth noch nicht konfiguriert";

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
      "Tesla OAuth ist fuer diese Installation noch nicht konfiguriert. Bitte zuerst TESLA_CLIENT_ID, TESLA_CLIENT_SECRET und die Fleet-Region setzen.";
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

  const sourceText = isLiveMode(payload.sync_mode) ? "Live Tesla" : "Demo";
  const deliveryText =
    payload.delivery_mode === "smtp"
      ? " Versand lief per SMTP."
      : payload.delivery_mode === "outbox"
        ? " Versand wurde nur im Outbox-Log protokolliert."
        : "";
  showNotice(
    `${sourceText}-Sync erfolgreich: ${payload.created_count} neue Rechnung(en), ${payload.skipped_count} bereits bekannt.${deliveryText}`
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
