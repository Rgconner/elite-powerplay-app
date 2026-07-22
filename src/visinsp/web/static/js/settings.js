/* Settings page - read and update global settings. */
(function () {
  "use strict";

  function load() {
    return window.App.api("/api/settings").then((d) => {
      const s = d.settings;
      const set = (id, v) => { const e = document.getElementById(id); if (e) e.value = v; };
      set("set-default-threshold", s.default_threshold);
      set("set-default-step", s.default_threshold_step);
      set("set-min", s.min_threshold);
      set("set-max", s.max_threshold);
      set("set-retention", s.retention_days);
      set("set-history-retention", s.history_retention_days);
      set("set-theme", s.theme);
    });
  }

  function save(e) {
    e.preventDefault();
    const get = (id) => document.getElementById(id).value;
    const body = {
      default_threshold:        parseFloat(get("set-default-threshold")),
      default_threshold_step:   parseFloat(get("set-default-step")),
      min_threshold:            parseFloat(get("set-min")),
      max_threshold:            parseFloat(get("set-max")),
      retention_days:           parseInt(get("set-retention"), 10),
      history_retention_days:   parseInt(get("set-history-retention"), 10),
      theme:                    get("set-theme"),
    };
    window.App.api("/api/settings", { method: "PUT", body })
      .then(() => window.App.toast({ title: "Settings saved", kind: "success" }))
      .catch((e) => window.App.toast({ title: "Save failed", body: e.message, kind: "error" }));
  }

  document.addEventListener("DOMContentLoaded", () => {
    load();
    document.getElementById("settings-form").addEventListener("submit", save);
  });
})();
