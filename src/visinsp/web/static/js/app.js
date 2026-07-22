/*
 * Visual Inspector — shared JS utilities.
 *
 * Provides:
 *   - A small fetch wrapper that returns parsed JSON
 *   - A toast() helper
 *   - A flash() helper (drives the .visual-flash overlay)
 *   - A socket.io client bootstrap (window.SOCKET)
 *   - A subscribe() helper for WebSocket events
 */

(function () {
  "use strict";

  const App = {
    socket: null,
    _subs: {},

    api(path, opts = {}) {
      const init = Object.assign(
        { headers: { "Content-Type": "application/json" }, credentials: "same-origin" },
        opts
      );
      if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
      return fetch(path, init).then(async (r) => {
        let data = null;
        try { data = await r.json(); } catch (_) { /* empty body ok */ }
        if (!r.ok) {
          const msg = (data && (data.message || data.error)) || r.statusText;
          const err = new Error(msg);
          err.status = r.status;
          err.body = data;
          throw err;
        }
        return data;
      });
    },

    toast({ title, body, kind = "info", duration = 5000 }) {
      const wrap = document.getElementById("toast-container");
      if (!wrap) return;
      const el = document.createElement("div");
      el.className = `app-toast app-toast--${kind}`;
      el.innerHTML =
        `<div class="app-toast__title"></div>` +
        `<div class="app-toast__body"></div>`;
      el.querySelector(".app-toast__title").textContent = title || "";
      el.querySelector(".app-toast__body").textContent = body || "";
      wrap.appendChild(el);
      setTimeout(() => {
        el.style.transition = "opacity 200ms";
        el.style.opacity = "0";
        setTimeout(() => el.remove(), 250);
      }, duration);
    },

    flash({ color = "red", duration = 1500, message = "" } = {}) {
      const overlay = document.getElementById("visual-flash");
      if (!overlay) return;
      const colors = {
        red:    "rgba(250, 77, 86, 0.30)",
        yellow: "rgba(241, 194, 27, 0.30)",
        green:  "rgba(66, 190, 101, 0.25)",
        blue:   "rgba(69, 137, 255, 0.30)",
      };
      overlay.style.background = colors[color] || colors.red;
      overlay.classList.add("visual-flash--active");
      if (message) this.toast({ title: "Inspection", body: message, kind: color === "green" ? "success" : "warning" });
      setTimeout(() => {
        overlay.style.background = "transparent";
        overlay.classList.remove("visual-flash--active");
      }, Math.max(200, duration));
    },

    initSocket() {
      if (typeof io !== "function") return null;
      try {
        this.socket = io({ transports: ["websocket", "polling"] });
        const subs = this._subs;
        Object.keys(subs).forEach((topic) => {
          this.socket.on(topic, (data) => subs[topic].forEach((cb) => cb(data)));
        });
        return this.socket;
      } catch (e) {
        console.warn("socket init failed", e);
        return null;
      }
    },

    subscribe(topic, cb) {
      if (!this._subs[topic]) this._subs[topic] = [];
      this._subs[topic].push(cb);
      if (this.socket) this.socket.on(topic, cb);
    },

    formatNumber(n, digits = 4) {
      if (n === null || n === undefined || Number.isNaN(n)) return "—";
      return Number(n).toFixed(digits);
    },
  };

  document.addEventListener("DOMContentLoaded", () => {
    App.initSocket();
  });

  window.App = App;
})();
