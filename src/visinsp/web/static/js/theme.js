/*
 * Theme toggle — flip between Carbon g100 (dark) and Carbon white.
 * Persists the choice in localStorage and POSTs it to /api/settings
 * so the server config stays in sync.
 */

(function () {
  "use strict";
  const KEY = "visinsp.theme";

  function setTheme(name) {
    document.body.classList.toggle("bx--theme--g100", name === "g100");
    document.body.classList.toggle("bx--theme--white", name === "white");
    document.querySelectorAll('link[rel="stylesheet"]').forEach((l) => {
      const href = l.getAttribute("href") || "";
      if (href.includes("/themes/css/white.css")) l.disabled = (name !== "white");
      if (href.includes("/themes/css/g100.css"))  l.disabled = (name === "white");
    });
    localStorage.setItem(KEY, name);
  }

  function current() {
    return localStorage.getItem(KEY) || "g100";
  }

  document.addEventListener("DOMContentLoaded", () => {
    setTheme(current());
    const btn = document.getElementById("theme-toggle");
    if (btn) {
      btn.addEventListener("click", () => {
        const next = current() === "g100" ? "white" : "g100";
        setTheme(next);
        // Sync to server (best-effort)
        if (window.App && window.App.api) {
          window.App.api("/api/settings", {
            method: "PUT",
            body: { theme: next },
          }).catch(() => {});
        }
      });
    }
  });
})();
