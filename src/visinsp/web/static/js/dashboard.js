/*
 * Dashboard page — system info, recent inspections table, camera refresh.
 */

(function () {
  "use strict";

  function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => {
      if (k === "class") e.className = v;
      else if (k.startsWith("data-")) e.setAttribute(k, v);
      else e.setAttribute(k, v);
    });
    children.flat().forEach((c) => {
      if (c == null) return;
      if (typeof c === "string") e.appendChild(document.createTextNode(c));
      else e.appendChild(c);
    });
    return e;
  }

  function loadContext() {
    return window.App.api("/api/settings/context").then((c) => {
      const set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
      set("info-env", c.environment || "—");
      set("info-gpio", c.gpio_backend || "—");
      set("info-schema", String(c.schema_version || "—"));
      set("info-config", c.config_path || "—");
      set("info-theme", c.theme || "—");
    });
  }

  function loadRecent() {
    return window.App.api("/api/inspections?limit=20").then((data) => {
      const tbody = document.querySelector("#recent-inspections tbody");
      if (!tbody) return;
      tbody.innerHTML = "";
      const rows = data.inspections || [];
      if (!rows.length) {
        tbody.appendChild(el("tr", {}, el("td", { colspan: 6, class: "bx--type-body-short-01" }, "No inspections yet.")));
        return;
      }
      rows.forEach((r) => {
        const tr = el("tr", {},
          el("td", {}, r.captured_at || "—"),
          el("td", {}, r.job_id || "—"),
          el("td", {}, window.App.formatNumber(r.score_overall)),
          el("td", {}, window.App.formatNumber(r.threshold)),
          el("td", {}, el("span", {
            class: r.passed ? "alert-row__verdict alert-row__verdict--valid" : "alert-row__verdict alert-row__verdict--false_negative",
          }, r.passed ? "Pass" : "Fail")),
          el("td", {},
            r.image_path
              ? el("img", {
                  class: "alert-row__thumb",
                  src: `/captures/${encodeURIComponent(r.image_path.split(/[\\/]/).pop())}`,
                  alt: "capture",
                })
              : el("span", { class: "bx--type-helper-text-01" }, "—")
          )
        );
        tbody.appendChild(tr);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadContext().catch(() => {});
    loadRecent().catch(() => {});
    if (window.App) {
      window.App.subscribe("inspection_complete", () => loadRecent());
    }
    const btn = document.getElementById("refresh-cameras-btn");
    if (btn) {
      btn.addEventListener("click", () => {
        window.App.api("/api/cameras/refresh", { method: "POST" })
          .then(() => window.App.toast({ title: "Cameras refreshed", kind: "success" }))
          .catch((e) => window.App.toast({ title: "Refresh failed", body: e.message, kind: "error" }));
      });
    }
  });
})();
