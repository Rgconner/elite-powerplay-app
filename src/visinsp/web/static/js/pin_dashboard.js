/*
 * Pin dashboard — shows every configured pin with its level, last edge
 * time, and (in mock mode) manual toggle / simulate buttons.
 *
 * Subscribes to WebSocket `pin_state` events for live updates; otherwise
 * polls /api/pins every 3s.
 */

(function () {
  "use strict";

  function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => {
      if (k === "class") e.className = v;
      else if (k.startsWith("data-")) e.setAttribute(k, v);
      else if (k === "html") e.innerHTML = v;
      else e.setAttribute(k, v);
    });
    children.flat().forEach((c) => {
      if (c == null) return;
      if (typeof c === "string") e.appendChild(document.createTextNode(c));
      else e.appendChild(c);
    });
    return e;
  }

  function renderRow(pin, backend) {
    const isInput = pin.direction === "input";
    const ledClass = `pin-led ${pin.level ? "pin-led--high" : "pin-led--low"} ${isInput ? "pin-led--input" : ""}`;
    const meta = `BCM ${pin.bcm} • ${pin.direction} • ${pin.edge || "—"}`;
    const row = el("div", { class: "pin-row", "data-pin-id": pin.id },
      el("div", {},
        el("span", { class: ledClass, title: pin.level ? "HIGH" : "LOW" }),
        el("span", { class: "pin-row__name" }, pin.name || pin.id),
        el("div", { class: "pin-row__meta" }, meta,
          pin.last_edge ? ` • last: ${pin.last_edge}` : ""
        )
      ),
      el("div", { class: "pin-btn-row" })
    );
    const btnWrap = row.querySelector(".pin-btn-row");
    if (isInput && backend === "mock") {
      const tg = el("button", { class: "bx--btn bx--btn--tertiary bx--btn--sm", type: "button" }, "Toggle");
      tg.addEventListener("click", () => {
        window.App.api(`/api/pins/${encodeURIComponent(pin.id)}/toggle`, { method: "POST" })
          .then(() => loadAndRender())
          .catch((e) => window.App.toast({ title: "Toggle failed", body: e.message, kind: "error" }));
      });
      btnWrap.appendChild(tg);
    } else if (!isInput) {
      const on = el("button", { class: "bx--btn bx--btn--tertiary bx--btn--sm", type: "button" }, "HIGH");
      const off = el("button", { class: "bx--btn bx--btn--ghost bx--btn--sm", type: "button" }, "LOW");
      on.addEventListener("click", () => window.App.api(`/api/pins/${encodeURIComponent(pin.id)}/set`, { method: "POST", body: { level: 1 } }).then(loadAndRender));
      off.addEventListener("click", () => window.App.api(`/api/pins/${encodeURIComponent(pin.id)}/set`, { method: "POST", body: { level: 0 } }).then(loadAndRender));
      btnWrap.appendChild(on);
      btnWrap.appendChild(off);
    }
    return row;
  }

  function loadAndRender() {
    const root = document.getElementById("pin-dashboard");
    if (!root) return;
    return window.App.api("/api/pins").then((data) => {
      root.innerHTML = "";
      if (!data.pins || !data.pins.length) {
        root.appendChild(el("p", { class: "bx--type-body-short-01" }, "No pins configured."));
        return;
      }
      data.pins.forEach((p) => root.appendChild(renderRow(p, data.backend)));
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadAndRender();
    setInterval(loadAndRender, 3000);
    if (window.App) {
      window.App.subscribe("pin_state", () => loadAndRender());
    }
  });

  // Expose for other pages that may include a pin tile.
  window.VisInspPins = { reload: loadAndRender };
})();
