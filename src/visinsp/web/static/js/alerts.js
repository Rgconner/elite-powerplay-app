/*
 * Alerts — list and dismiss with VP/FP/FN verdicts.
 *
 * Renders an alert list into a #alerts-table tbody, and also supports a
 * smaller "recent" list via #recent-alerts on the dashboard.
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

  function verdictBadge(v) {
    if (v === "valid") return "Valid";
    if (v === "false_positive") return "False positive";
    if (v === "false_negative") return "False negative";
    return "Pending";
  }

  function buildActionsCell(alert) {
    const cell = el("td", { class: "alert-row__actions" });
    const mkBtn = (label, verdict, kind) => {
      const b = el("button", {
        class: `bx--btn bx--btn--${kind} bx--btn--sm`,
        type: "button",
        "data-verdict": verdict,
        disabled: alert.verdict && alert.verdict !== "pending" ? "true" : null,
      }, label);
      b.addEventListener("click", () => dismiss(alert.id, verdict));
      return b;
    };
    cell.appendChild(mkBtn("Valid", "valid", "primary"));
    cell.appendChild(mkBtn("False pos.", "false_positive", "danger--tertiary"));
    cell.appendChild(mkBtn("False neg.", "false_negative", "warning--tertiary"));
    return cell;
  }

  function dismiss(alertId, verdict) {
    return window.App.api(`/api/alerts/${alertId}/dismiss`, {
      method: "POST",
      body: { verdict, actor: "ui" },
    })
      .then((res) => {
        window.App.toast({
          title: "Alert dismissed",
          body: res.changed
            ? `Threshold ${verdict === "false_positive" ? "raised" : "lowered"} → ${(res.new_threshold || 0).toFixed(4)}`
            : "No threshold change",
          kind: "success",
        });
        return reloadAll();
      })
      .catch((e) => window.App.toast({ title: "Dismiss failed", body: e.message, kind: "error" }));
  }

  function renderTable(tbody, alerts) {
    tbody.innerHTML = "";
    if (!alerts || !alerts.length) {
      tbody.appendChild(el("tr", {},
        el("td", { colspan: 7, class: "bx--type-body-short-01" }, "No alerts.")));
      return;
    }
    alerts.forEach((a) => {
      const tr = el("tr", { "data-alert-id": a.id });
      tr.appendChild(el("td", {}, a.raised_at || "—"));
      tr.appendChild(el("td", {}, a.job_id || "—"));
      tr.appendChild(el("td", {}, window.App.formatNumber(a.score)));
      tr.appendChild(el("td", {}, window.App.formatNumber(a.threshold)));
      const imgTd = el("td", {});
      if (a.image_path) {
        const fname = a.image_path.split(/[\\/]/).pop();
        imgTd.appendChild(el("img", {
          class: "alert-row__thumb",
          src: `/captures/${encodeURIComponent(fname)}`,
          alt: "capture",
        }));
      } else {
        imgTd.appendChild(el("span", { class: "bx--type-helper-text-01" }, "—"));
      }
      tr.appendChild(imgTd);
      tr.appendChild(el("td", { class: `alert-row__verdict alert-row__verdict--${a.verdict}` }, verdictBadge(a.verdict)));
      tr.appendChild(buildActionsCell(a));
      tbody.appendChild(tr);
    });
  }

  function renderRecentList(ul, alerts) {
    ul.innerHTML = "";
    if (!alerts || !alerts.length) {
      ul.appendChild(el("li", { class: "bx--type-body-short-01" }, "No alerts yet."));
      return;
    }
    alerts.slice(0, 5).forEach((a) => {
      const li = el("li", {},
        el("strong", {}, a.job_id || "—"),
        ` score ${window.App.formatNumber(a.score)} (thresh ${window.App.formatNumber(a.threshold)}) — `,
        el("span", { class: `alert-row__verdict alert-row__verdict--${a.verdict}` }, verdictBadge(a.verdict))
      );
      ul.appendChild(li);
    });
  }

  function reloadAll() {
    const table = document.getElementById("alerts-table");
    const recent = document.getElementById("recent-alerts");
    const filterEl = document.getElementById("verdict-filter");
    const verdict = filterEl ? filterEl.value : "";
    const qs = verdict ? `?verdict=${encodeURIComponent(verdict)}&limit=100` : "?limit=100";
    return window.App.api("/api/alerts" + qs).then((data) => {
      if (table) renderTable(table.querySelector("tbody"), data.alerts);
      if (recent) renderRecentList(recent, data.alerts);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    reloadAll();
    const filterEl = document.getElementById("verdict-filter");
    if (filterEl) filterEl.addEventListener("change", reloadAll);
    const refresh = document.getElementById("refresh-alerts");
    if (refresh) refresh.addEventListener("click", reloadAll);
    if (window.App) {
      window.App.subscribe("alert_new", () => reloadAll());
      window.App.subscribe("alert_resolved", () => reloadAll());
    }
  });

  window.VisInspAlerts = { reload: reloadAll };
})();
