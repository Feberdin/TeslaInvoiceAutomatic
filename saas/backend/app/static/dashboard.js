/* Purpose: Drive the authenticated dashboard for VINs, recipients, invoice sync and SMTP tests.
Input/Output: Reads the current session from the backend, updates the UI and triggers user actions.
Invariants: Every request relies on the session cookie, so the user never has to type their e-mail repeatedly.
Debug: If actions fail, inspect the API response body and whether the session has expired. */

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
    const message = payload?.detail || payload?.message || "Die Anfrage ist fehlgeschlagen.";
    throw new Error(message);
  }

  return payload;
}

function showNotice(message, type = "info") {
  const target = document.getElementById("notice");
  target.className = `notice ${type}`;
  target.textContent = message;
  target.hidden = false;
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
    const card = document.createElement("div");
    card.className = "list-item";
    card.innerHTML = `
      <div>
        <strong>${vehicle.nickname}</strong>
        <div class="helper">${vehicle.vin} · ${vehicle.model}</div>
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
    body.innerHTML = '<tr><td colspan="6">Noch keine Rechnungen vorhanden. Fuehre zuerst einen Test-Sync aus.</td></tr>';
    return;
  }

  for (const invoice of invoices) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${invoice.invoice_id}</td>
      <td>${new Date(invoice.charge_started_at).toLocaleString("de-DE")}</td>
      <td>${invoice.vehicle_name}</td>
      <td>${invoice.location}</td>
      <td>${invoice.amount.toFixed(2)} ${invoice.currency}</td>
      <td><a class="button-link secondary" href="${invoice.pdf_download_url}">PDF laden</a></td>
    `;
    body.appendChild(row);
  }
}

async function refreshDashboard() {
  const profile = await apiRequest("/api/v1/me");
  document.getElementById("current-email").textContent = profile.email;
  document.getElementById("metric-vehicles").textContent = String(profile.vehicle_count);
  document.getElementById("metric-invoices").textContent = String(profile.invoice_count);
  document.getElementById("metric-sync").textContent = profile.last_synced_at
    ? new Date(profile.last_synced_at).toLocaleString("de-DE")
    : "noch nie";
  document.getElementById("metric-delivery").textContent = profile.smtp_configured ? "SMTP aktiv" : "Outbox";

  document.getElementById("recipients").value = profile.email_recipients.join(", ");
  document.getElementById("subject-template").value = profile.subject_template;
  document.getElementById("attach-pdf").checked = profile.attach_pdf;
  renderAccountingOptions(profile.available_accounting_targets, profile.accounting_targets);
  renderVehicles(profile.vehicles);

  const invoices = await apiRequest("/api/v1/invoices");
  renderInvoices(invoices);
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
    body: JSON.stringify({ include_fresh_demo_invoice: true }),
  });
  const deliveryText =
    payload.delivery_mode === "smtp"
      ? " Versand lief per SMTP."
      : payload.delivery_mode === "outbox"
        ? " Versand wurde nur im Outbox-Log protokolliert."
        : "";
  showNotice(
    `Sync erfolgreich: ${payload.created_count} neue Rechnung(en), ${payload.skipped_count} bereits bekannt.${deliveryText}`
  );
  await refreshDashboard();
}

async function logout() {
  await apiRequest("/api/v1/auth/logout", { method: "POST" });
  window.location.href = "/auth";
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("logout-button").addEventListener("click", () =>
    logout().catch((error) => showNotice(error.message, "error"))
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
    runSync().catch((error) => showNotice(error.message, "error"))
  );

  try {
    await refreshDashboard();
  } catch (error) {
    showNotice(error.message, "error");
  }
});
