/* Purpose: Drive the simple browser dashboard without introducing a separate frontend build step.
Input/Output: Reads form values, calls the JSON API and updates the visible status and invoice list.
Invariants: Every action shows feedback, and the invoice table is always refreshed from the server afterwards.
Debug: If buttons appear to do nothing, open the browser console and network tab to inspect the requests. */

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : null;

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

function hideNotice() {
  const target = document.getElementById("notice");
  target.hidden = true;
}

function currentUserEmail() {
  return document.getElementById("user-email").value.trim().toLowerCase();
}

function currentRecipients() {
  return document
    .getElementById("recipients")
    .value.split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

async function refreshDashboard() {
  const userEmail = currentUserEmail();
  if (!userEmail) {
    return;
  }

  const status = await apiRequest(`/api/v1/status?user_email=${encodeURIComponent(userEmail)}`);
  document.getElementById("metric-user").textContent = status.user_exists ? "bereit" : "neu";
  document.getElementById("metric-tesla").textContent = status.tesla_connected ? "verbunden" : "offen";
  document.getElementById("metric-vehicles").textContent = String(status.vehicle_count);
  document.getElementById("metric-invoices").textContent = String(status.invoice_count);
  document.getElementById("metric-sync").textContent = status.last_synced_at
    ? new Date(status.last_synced_at).toLocaleString("de-DE")
    : "noch nie";
  document.getElementById("recipients-preview").textContent = status.email_recipients.length
    ? status.email_recipients.join(", ")
    : "Noch keine Empfänger gespeichert";

  const invoices = await apiRequest(`/api/v1/invoices?user_email=${encodeURIComponent(userEmail)}`);
  const body = document.getElementById("invoice-body");
  body.innerHTML = "";

  if (!invoices.length) {
    body.innerHTML = '<tr><td colspan="6">Noch keine Rechnungen vorhanden. Fuehre zuerst einen Sync aus.</td></tr>';
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
      <td><a class="button-link secondary" href="${invoice.pdf_download_url}?user_email=${encodeURIComponent(userEmail)}">PDF laden</a></td>
    `;
    body.appendChild(row);
  }
}

async function createUser() {
  const email = currentUserEmail();
  await apiRequest("/api/v1/demo/users", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  showNotice("Demo-Nutzer wurde vorbereitet.");
  await refreshDashboard();
}

async function connectTesla() {
  const userEmail = currentUserEmail();
  await apiRequest("/api/v1/demo/tesla/connect", {
    method: "POST",
    body: JSON.stringify({ user_email: userEmail, vehicle_count: 2 }),
  });
  showNotice("Demo-Tesla-Konto wurde verbunden.");
  await refreshDashboard();
}

async function saveRecipients() {
  const userEmail = currentUserEmail();
  const recipients = currentRecipients();
  await apiRequest("/api/v1/settings/email", {
    method: "POST",
    body: JSON.stringify({
      user_email: userEmail,
      recipients,
      subject_template: "Neue Tesla-Rechnungen fuer {email}",
      attach_pdf: true,
    }),
  });
  showNotice("Empfaenger wurden gespeichert.");
  await refreshDashboard();
}

async function runSync() {
  const userEmail = currentUserEmail();
  const payload = await apiRequest("/api/v1/sync/run", {
    method: "POST",
    body: JSON.stringify({ user_email: userEmail }),
  });
  showNotice(
    `Sync erfolgreich: ${payload.created_count} neue Rechnung(en), ${payload.skipped_count} bereits bekannt.`
  );
  await refreshDashboard();
}

document.addEventListener("DOMContentLoaded", async () => {
  const userInput = document.getElementById("user-email");
  userInput.addEventListener("change", () => refreshDashboard().catch((error) => showNotice(error.message, "error")));

  document.getElementById("create-user").addEventListener("click", () =>
    createUser().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("connect-tesla").addEventListener("click", () =>
    connectTesla().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("save-recipients").addEventListener("click", () =>
    saveRecipients().catch((error) => showNotice(error.message, "error"))
  );
  document.getElementById("run-sync").addEventListener("click", () =>
    runSync().catch((error) => showNotice(error.message, "error"))
  );

  hideNotice();
  try {
    await refreshDashboard();
  } catch (error) {
    showNotice(error.message, "error");
  }
});

