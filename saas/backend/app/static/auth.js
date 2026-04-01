/* Purpose: Keep the Google-only auth page lightweight and resilient.
Input/Output: Reads query-string notices and exposes them in the page without owning the actual OAuth redirect.
Invariants: The primary Google CTA is a normal anchor link, so login still starts even when JavaScript fails.
Debug: If users loop back to /auth, inspect the query string, rendered Google link and backend cookie/session logs. */

function showNotice(message, type = "info") {
  if (window.AppNoticeCenter?.show) {
    window.AppNoticeCenter.show(message, type);
  }
}

function consumeQueryNotices() {
  const params = new URLSearchParams(window.location.search);
  const googleError = params.get("google_error");
  if (googleError) {
    showNotice(googleError, "error");
    window.history.replaceState({}, document.title, "/auth");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  consumeQueryNotices();
  const googleLoginLink = document.getElementById("google-login-link");
  if (googleLoginLink && !googleLoginLink.getAttribute("href")) {
    googleLoginLink.setAttribute("href", "/api/v1/auth/google/start");
  }
});
