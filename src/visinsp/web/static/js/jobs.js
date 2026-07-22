/* Jobs page - list, create, edit, action editor. Compact vanilla JS. */
(function () {
  "use strict";

  const state = {
    pins: [], jobs: [], references: [], cameras: [],
    formActions: { fail: [], pass: [] },
  };

  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "class") e.className = v;
      else if (k === "html") e.innerHTML = v;
      else e.setAttribute(k, v);
    });
    kids.flat().forEach((c) => {
      if (c == null) return;
      e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return e;
  }

  function blankAction(type) {
    if (type === "gpio") return { type, pin_id: "", mode: "HIGH", duration_ms: 500 };
    if (type === "sound") return { type, wav: "", frequency_hz: 1000, duration_ms: 300 };
    if (type === "visual") return { type, color: "red", duration_ms: 1500, message: "" };
    if (type === "notification") return { type, title: "Inspection Alert", body: "", kind: "error" };
    return { type };
  }

  function actionRow(kind, action, idx) {
    const wrap = el("div", { class: "app-action-row", "data-idx": idx });
    wrap.style.cssText = "border:1px solid #393939;padding:0.5rem;margin-bottom:0.5rem;border-radius:2px;display:grid;grid-template-columns:1fr 1fr 1fr 1fr auto;gap:0.5rem;align-items:center;";
    const typeSel = el("select", { class: "bx--select-input" });
    ["gpio", "sound", "visual", "notification"].forEach((t) => {
      const o = el("option", { value: t }, t);
      if (t === action.type) o.setAttribute("selected", "true");
      typeSel.appendChild(o);
    });
    typeSel.addEventListener("change", (e) => {
      const fresh = blankAction(e.target.value);
      Object.keys(fresh).forEach((k) => { if (!(k in action)) action[k] = fresh[k]; });
      action.type = e.target.value;
      rebuildActionEditor(kind, idx);
    });
    wrap.appendChild(typeSel);

    const detail = el("div", { class: "app-action-detail" });
    detail.style.gridColumn = "1 / -1";
    detail.appendChild(actionDetailUI(action, kind, idx));
    wrap.appendChild(detail);

    const rm = el("button", { class: "bx--btn bx--btn--danger--ghost bx--btn--sm", type: "button" }, "Remove");
    rm.addEventListener("click", () => {
      state.formActions[kind].splice(idx, 1);
      rebuildActionEditor(kind);
    });
    wrap.appendChild(rm);
    return wrap;
  }

  function actionDetailUI(action, kind, idx) {
    if (action.type === "gpio") {
      const pinSel = el("select", { class: "bx--select-input" });
      state.pins.filter((p) => p.direction === "output").forEach((p) => {
        const o = el("option", { value: p.id }, `${p.name} (BCM ${p.bcm})`);
        if (p.id === action.pin_id) o.setAttribute("selected", "true");
        pinSel.appendChild(o);
      });
      pinSel.addEventListener("change", (e) => { action.pin_id = e.target.value; });
      const modeSel = el("select", { class: "bx--select-input" });
      ["HIGH", "LOW", "PULSE"].forEach((m) => {
        const o = el("option", { value: m }, m);
        if (m === action.mode) o.setAttribute("selected", "true");
        modeSel.appendChild(o);
      });
      modeSel.addEventListener("change", (e) => { action.mode = e.target.value; });
      const ms = el("input", { class: "bx--text-input bx--number", type: "number", min: 50, step: 50, value: action.duration_ms || 500 });
      ms.addEventListener("input", (e) => { action.duration_ms = +e.target.value; });
      return el("div", { style: "display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.5rem;" },
        el("label", {}, "Pin:", pinSel),
        el("label", {}, "Mode:", modeSel),
        el("label", {}, "Pulse ms:", ms)
      );
    }
    if (action.type === "sound") {
      const wav = el("input", { class: "bx--text-input", type: "text", value: action.wav || "", placeholder: "(default beep)" });
      wav.addEventListener("input", (e) => { action.wav = e.target.value; });
      const freq = el("input", { class: "bx--text-input bx--number", type: "number", min: 100, max: 5000, value: action.frequency_hz });
      freq.addEventListener("input", (e) => { action.frequency_hz = +e.target.value; });
      const dur = el("input", { class: "bx--text-input bx--number", type: "number", min: 50, value: action.duration_ms });
      dur.addEventListener("input", (e) => { action.duration_ms = +e.target.value; });
      return el("div", { style: "display:grid;grid-template-columns:2fr 1fr 1fr;gap:0.5rem;" },
        el("label", {}, "WAV file:", wav),
        el("label", {}, "Freq Hz:", freq),
        el("label", {}, "Dur ms:", dur)
      );
    }
    if (action.type === "visual") {
      const colorSel = el("select", { class: "bx--select-input" });
      ["red", "yellow", "green", "blue"].forEach((c) => {
        const o = el("option", { value: c }, c);
        if (c === action.color) o.setAttribute("selected", "true");
        colorSel.appendChild(o);
      });
      colorSel.addEventListener("change", (e) => { action.color = e.target.value; });
      const dur = el("input", { class: "bx--text-input bx--number", type: "number", min: 100, value: action.duration_ms });
      dur.addEventListener("input", (e) => { action.duration_ms = +e.target.value; });
      const msg = el("input", { class: "bx--text-input", type: "text", value: action.message || "", placeholder: "Optional message" });
      msg.addEventListener("input", (e) => { action.message = e.target.value; });
      return el("div", { style: "display:grid;grid-template-columns:1fr 1fr 2fr;gap:0.5rem;" },
        el("label", {}, "Color:", colorSel),
        el("label", {}, "Dur ms:", dur),
        el("label", {}, "Message:", msg)
      );
    }
    if (action.type === "notification") {
      const title = el("input", { class: "bx--text-input", type: "text", value: action.title });
      title.addEventListener("input", (e) => { action.title = e.target.value; });
      const body = el("input", { class: "bx--text-input", type: "text", value: action.body, placeholder: "Body" });
      body.addEventListener("input", (e) => { action.body = e.target.value; });
      const kindSel = el("select", { class: "bx--select-input" });
      ["error", "warning", "info", "success"].forEach((k) => {
        const o = el("option", { value: k }, k);
        if (k === action.kind) o.setAttribute("selected", "true");
        kindSel.appendChild(o);
      });
      kindSel.addEventListener("change", (e) => { action.kind = e.target.value; });
      return el("div", { style: "display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.5rem;" },
        el("label", {}, "Title:", title),
        el("label", {}, "Kind:", kindSel),
        el("label", {}, "Body:", body)
      );
    }
    return el("span", { class: "bx--type-helper-text-01" }, "Unknown action type");
  }

  function rebuildActionEditor(kind, onlyIdx) {
    const root = document.getElementById("actions-" + kind);
    if (!root) return;
    if (onlyIdx !== undefined) {
      const row = root.querySelector(`[data-idx="${onlyIdx}"]`);
      if (row) {
        const detail = row.querySelector(".app-action-detail");
        detail.innerHTML = "";
        detail.appendChild(actionDetailUI(state.formActions[kind][onlyIdx], kind, onlyIdx));
      }
      return;
    }
    root.innerHTML = "";
    state.formActions[kind].forEach((a, i) => root.appendChild(actionRow(kind, a, i)));
  }

  function addAction(kind, type) {
    state.formActions[kind].push(blankAction(type || "gpio"));
    rebuildActionEditor(kind);
  }

  function loadForm(job) {
    document.getElementById("job-id").value = job && job.id ? job.id : "";
    document.getElementById("job-name").value = job && job.name || "";
    document.getElementById("job-reference").value = job && job.reference_id || "";
    document.getElementById("job-camera").value = job && job.camera_id || "";
    document.getElementById("job-threshold").value = job && job.threshold != null ? job.threshold : 0.85;
    document.getElementById("job-threshold-step").value = job && job.threshold_step != null ? job.threshold_step : 0.005;
    document.getElementById("job-enabled").checked = job ? !!job.enabled : true;
    state.formActions.fail = (job && job.actions_on_fail || []).map((a) => Object.assign({}, a));
    state.formActions.pass = (job && job.actions_on_pass || []).map((a) => Object.assign({}, a));
    rebuildActionEditor("fail");
    rebuildActionEditor("pass");
  }

  function collectForm() {
    return {
      id: document.getElementById("job-id").value || undefined,
      name: document.getElementById("job-name").value,
      reference_id: document.getElementById("job-reference").value,
      camera_id: document.getElementById("job-camera").value,
      threshold: parseFloat(document.getElementById("job-threshold").value),
      threshold_step: parseFloat(document.getElementById("job-threshold-step").value),
      enabled: document.getElementById("job-enabled").checked,
      actions_on_fail: state.formActions.fail,
      actions_on_pass: state.formActions.pass,
    };
  }

  function fillSelects() {
    const refSel = document.getElementById("job-reference");
    refSel.innerHTML = "";
    state.references.forEach((r) => refSel.appendChild(el("option", { value: r.id }, r.name)));
    const camSel = document.getElementById("job-camera");
    camSel.innerHTML = "";
    state.cameras.forEach((c) => camSel.appendChild(el("option", { value: c.id }, c.name)));
  }

  function loadJobs() {
    return window.App.api("/api/jobs").then((d) => {
      state.jobs = d.jobs || [];
      const tbody = document.querySelector("#jobs-table tbody");
      tbody.innerHTML = "";
      if (!state.jobs.length) {
        tbody.appendChild(el("tr", {}, el("td", { colspan: 7, class: "bx--type-body-short-01" }, "No jobs.")));
        return;
      }
      state.jobs.forEach((j) => {
        const tr = el("tr", {},
          el("td", {}, j.name),
          el("td", {}, j.reference_id),
          el("td", {}, j.camera_id),
          el("td", {}, window.App.formatNumber(j.threshold, 3)),
          el("td", {}, window.App.formatNumber(j.threshold_step, 4)),
          el("td", {}, j.enabled ? "yes" : "no"),
          el("td", {},
            el("button", { class: "bx--btn bx--btn--tertiary bx--btn--sm", type: "button" }, "Edit"),
            el("button", { class: "bx--btn bx--btn--danger--ghost bx--btn--sm", type: "button" }, "Del")
          )
        );
        const [editBtn, delBtn] = tr.querySelectorAll("button");
        editBtn.addEventListener("click", () => loadForm(j));
        delBtn.addEventListener("click", () => {
          if (!confirm(`Delete job "${j.name}"?`)) return;
          window.App.api(`/api/jobs/${encodeURIComponent(j.id)}`, { method: "DELETE" }).then(loadJobs);
        });
        tbody.appendChild(tr);
      });
    });
  }

  function saveJob(e) {
    e.preventDefault();
    const body = collectForm();
    const isUpdate = !!body.id;
    window.App.api("/api/jobs" + (isUpdate ? "/" + encodeURIComponent(body.id) : ""), {
      method: isUpdate ? "PUT" : "POST",
      body: isUpdate ? body : Object.assign({}, body, { id: undefined }),
    })
      .then(() => {
        window.App.toast({ title: isUpdate ? "Job updated" : "Job created", kind: "success" });
        return loadJobs();
      })
      .then(() => loadForm(null))
      .catch((e) => window.App.toast({ title: "Save failed", body: e.message, kind: "error" }));
  }

  function runNow() {
    const id = document.getElementById("job-id").value;
    if (!id) {
      window.App.toast({ title: "Save the job first", kind: "warning" });
      return;
    }
    window.App.api("/api/inspections/run", { method: "POST", body: { job_id: id } })
      .then((d) => {
        const r = d.inspection;
        window.App.toast({
          title: r.passed ? "Pass" : "Fail",
          body: `Score ${window.App.formatNumber(r.score_overall)} / thresh ${window.App.formatNumber(r.threshold)}`,
          kind: r.passed ? "success" : "warning",
        });
        if (window.App.flash) window.App.flash({ color: r.passed ? "green" : "red", duration: 1500 });
      })
      .catch((e) => window.App.toast({ title: "Run failed", body: e.message, kind: "error" }));
  }

  document.addEventListener("DOMContentLoaded", () => {
    Promise.all([
      window.App.api("/api/pins").then((d) => { state.pins = d.pins || []; }),
      window.App.api("/api/cameras").then((d) => { state.cameras = d.cameras || []; }),
      window.App.api("/api/references").then((d) => { state.references = d.references || []; }),
    ]).then(() => {
      fillSelects();
      loadForm(null);
      loadJobs();
    });

    document.getElementById("job-form").addEventListener("submit", saveJob);
    document.getElementById("new-job").addEventListener("click", () => loadForm(null));
    document.getElementById("run-job").addEventListener("click", runNow);
    document.getElementById("add-action-fail").addEventListener("click", () => addAction("fail", "gpio"));
    document.getElementById("add-action-pass").addEventListener("click", () => addAction("pass", "notification"));
  });
})();
