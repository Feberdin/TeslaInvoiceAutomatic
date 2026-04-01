/* Purpose: Handle registration and login without a frontend build step.
Input/Output: Sends credentials to the auth API and redirects into the dashboard on success.
Invariants: Success always means the session cookie is already set by the backend.
Debug: If the redirect loops back to /auth, inspect the auth API response and browser cookies. */

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
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

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("register-form").addEventListener("submit", async (event) => {
    event.preventDefault();

    try {
      await apiRequest("/api/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({
          email: document.getElementById("register-email").value,
          password: document.getElementById("register-password").value,
        }),
      });
      window.location.href = "/dashboard";
    } catch (error) {
      showNotice(error.message, "error");
    }
  });

  document.getElementById("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();

    try {
      await apiRequest("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: document.getElementById("login-email").value,
          password: document.getElementById("login-password").value,
        }),
      });
      window.location.href = "/dashboard";
    } catch (error) {
      showNotice(error.message, "error");
    }
  });
});
