/* Purpose: Provide one shared overlay for temporary success/error hints across auth, dashboard and admin pages.
Input/Output: Page scripts push plain text messages into this center; the overlay renders them, auto-hides them and keeps a reopenable log.
Invariants: Messages never disappear permanently unless the user clears the log, and hovering the open overlay pauses auto-hide.
Debug: If no notices appear, inspect the `#app-notice-*` elements from `base.html` and confirm this file is loaded before page actions fire. */

(() => {
  const AUTO_HIDE_MS = 7000;
  const MAX_ENTRIES = 30;

  let entries = [];
  let isPanelOpen = false;
  let autoHideTimer = null;
  let isHovered = false;
  let sequence = 0;
  let elementsBound = false;

  function ensureElements() {
    const shell = document.getElementById("app-notice-shell");
    const toggleButton = document.getElementById("app-notice-toggle");
    const panel = document.getElementById("app-notice-panel");
    const list = document.getElementById("app-notice-list");
    const clearButton = document.getElementById("app-notice-clear");
    const closeButton = document.getElementById("app-notice-close");

    if (!shell || !toggleButton || !panel || !list || !clearButton || !closeButton) {
      return null;
    }

    return { shell, toggleButton, panel, list, clearButton, closeButton };
  }

  function clearTimer() {
    if (autoHideTimer !== null) {
      window.clearTimeout(autoHideTimer);
      autoHideTimer = null;
    }
  }

  function scheduleAutoHide() {
    clearTimer();
    if (!isPanelOpen || isHovered || !entries.length) {
      return;
    }

    autoHideTimer = window.setTimeout(() => {
      isPanelOpen = false;
      render();
    }, AUTO_HIDE_MS);
  }

  function formatTime(timestamp) {
    return new Intl.DateTimeFormat("de-DE", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(timestamp);
  }

  function normalizeMessage(message) {
    if (typeof message !== "string") {
      return "";
    }
    return message.trim();
  }

  function render() {
    const elements = ensureElements();
    if (!elements) {
      return;
    }

    const { shell, toggleButton, panel, list } = elements;
    const hasEntries = entries.length > 0;

    shell.hidden = !hasEntries;
    toggleButton.hidden = !hasEntries;
    toggleButton.textContent = isPanelOpen ? "Log schliessen" : `Log${hasEntries ? ` (${entries.length})` : ""}`;
    panel.hidden = !hasEntries || !isPanelOpen;
    list.innerHTML = "";

    for (const entry of entries) {
      const card = document.createElement("article");
      card.className = `overlay-notice-entry ${entry.type}`;
      card.innerHTML = `
        <div class="overlay-notice-entry-head">
          <span class="overlay-notice-badge">${entry.type === "error" ? "Fehler" : "Info"}</span>
          <time>${formatTime(entry.createdAt)}</time>
        </div>
        <p>${entry.message}</p>
      `;
      list.appendChild(card);
    }
  }

  function bindOnce() {
    if (elementsBound) {
      return;
    }
    const elements = ensureElements();
    if (!elements) {
      return;
    }

    elements.toggleButton.addEventListener("click", () => {
      isPanelOpen = !isPanelOpen;
      render();
      scheduleAutoHide();
    });
    elements.closeButton.addEventListener("click", () => {
      isPanelOpen = false;
      render();
      clearTimer();
    });
    elements.clearButton.addEventListener("click", () => {
      entries = [];
      isPanelOpen = false;
      render();
      clearTimer();
    });
    elements.panel.addEventListener("mouseenter", () => {
      isHovered = true;
      clearTimer();
    });
    elements.panel.addEventListener("mouseleave", () => {
      isHovered = false;
      scheduleAutoHide();
    });

    elementsBound = true;
  }

  function show(message, type = "info") {
    const normalized = normalizeMessage(message);
    if (!normalized) {
      return;
    }

    bindOnce();
    entries = [
      {
        id: `notice-${Date.now()}-${sequence += 1}`,
        type: type === "error" ? "error" : "info",
        message: normalized,
        createdAt: new Date(),
      },
      ...entries,
    ].slice(0, MAX_ENTRIES);
    isPanelOpen = true;
    render();
    scheduleAutoHide();
  }

  function open() {
    if (!entries.length) {
      return;
    }
    bindOnce();
    isPanelOpen = true;
    render();
    scheduleAutoHide();
  }

  document.addEventListener("DOMContentLoaded", bindOnce);
  window.AppNoticeCenter = { show, open };
})();
