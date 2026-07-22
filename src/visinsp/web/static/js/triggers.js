/* Triggers page - list and CRUD pin -> job mappings. */
(function () {
  "use strict";

  const state = { pins: [], jobs: [], triggers: [] };

  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "class") e.className = v;
      else e.setAttribute(k, v);
    });
    kids.flat().forEach((c) => {
      if (c == null) return;
      e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return e;
  }

  function fillSelects() {
    const pinSel = document.getElementById("trig-pin");
    pinSel.innerHTML = "";
    state.pins.filter((p) => p.direction === "input").forEach((p) =>
      pinSel.appendChild(el("option", { value: p.id }, `${p.name} (BCM ${p.bcm})`))
    );
    const jobSel = document.getElementById("trig-job");
    jobSel.innerHTML = "";
    state.jobs.forEach((j) => jobSel.appendChild(el("option", { value: j.id }, j.name)));
  }

  function loadTriggers() {
    return window.App.api("/api/triggers").then((d) => {
      state.triggers = d.triggers || [];
      const tbody = document.querySelector("#triggers-table tbody");
      tbody.innerHTML = "";
      if (!state.triggers.length) {
        tbody.appendChild(el("tr", {}, el("td", { colspan: 6, class: "bx--type-body-short-01" }, "No triggers.")));
        return;
      }
      state.triggers.forEach((t) => {
        const pin = state.pins.find((p) => p.id === t.pin_id);
        const job = state.jobs.find((j) => j.id === t.job_id);
        const tr = el("tr", {},
          el("td", {}, t.name || "—"),
          el("td", {}, pin ? `${pin.name} (BCM ${pin.bcm})` : t.pin_id),
          el("td", {}, job ? job.name : t.job_id),
          el("td", {}, t.edge),
          el("td", {}, t.enabled ? "yes" : "no"),
          el("td", {},
            el("button", { class: "bx--btn bx--btn--tertiary bx--btn--sm", type: "button" }, "Edit"),
            el("button", { class: "bx--btn bx--btn--danger--ghost bx--btn--sm", type: "button" }, "Del")
          )
        );
        const [editBtn, delBtn] = tr.querySelectorAll("button");
        editBtn.addEventListener("click", () => {
          document.getElementById("trig-id").value = t.id;
          document.getElementById("trig-name").value = t.name || "";
          document.getElementById("trig-pin").value = t.pin_id;
          document.getElementById("trig-job").value = t.job_id;
          document.getElementById("trig-edge").value = t.edge || "falling";
        });
        delBtn.addEventListener("click", () => {
          if (!confirm("Delete trigger?")) return;
          window.App.api(`/api/triggers/${encodeURIComponent(t.id)}`, { method: "DELETE" })
            .then(loadTriggers)
            .catch((e) => window.App.toast({ title: "Delete failed", body: e.message, kind: "error" }));
        });
        tbody.appendChild(tr);
      });
    });
  }

  function saveTrigger(e) {
    e.preventDefault();
    const body = {
      id: document.getElementById("trig-id").value || undefined,
      name: document.getElementById("trig-name").value,
      pin_id: document.getElementById("trig-pin").value,
      job_id: document.getElementById("trig-job").value,
      edge: document.getElementById("trig-edge").value,
      enabled: true,
    };
    window.App.api("/api/triggers", { method: "POST", body })
      .then(() => {
        window.App.toast({ title: "Trigger saved", kind: "success" });
        document.getElementById("trigger-form").reset();
        document.getElementById("trig-edge").value = "falling";
        return loadTriggers();
      })
      .catch((e) => window.App.toast({ title: "Save failed", body: e.message, kind: "error" }));
  }

  function fireTrigger() {
    const id = document.getElementById("trig-id").value;
    if (!id) {
      window.App.toast({ title: "Load a trigger first", kind: "warning" });
      return;
    }
    window.App.api(`/api/triggers/simulate/${encodeURIComponent(id)}`, { method: "POST" })
      .then(() => window.App.toast({ title: "Trigger fired", kind: "info" }))
      .catch((e) => window.App.toast({ title: "Fire failed", body: e.message, kind: "error" }));
  }

  document.addEventListener("DOMContentLoaded", () => {
    Promise.all([
      window.App.api("/api/pins").then((d) => { state.pins = d.pins || []; }),
      window.App.api("/api/jobs").then((d) => { state.jobs = d.jobs || []; }),
    ]).then(() => { fillSelects(); loadTriggers(); });
    document.getElementById("trigger-form").addEventListener("submit", saveTrigger);
    document.getElementById("fire-trigger").addEventListener("click", fireTrigger);
  });
})();
