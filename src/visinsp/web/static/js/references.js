/*
 * References list page — list, capture-from-camera, edit, delete.
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

  function loadCameras() {
    return window.App.api("/api/cameras").then((data) => {
      const sel = document.getElementById("capture-camera");
      if (!sel) return;
      sel.innerHTML = "";
      (data.cameras || []).forEach((c) => {
        sel.appendChild(el("option", { value: c.id }, `${c.name} (${c.id})`));
      });
    });
  }

  function loadReferences() {
    const root = document.getElementById("reference-list");
    return window.App.api("/api/references").then((data) => {
      root.innerHTML = "";
      const refs = data.references || [];
      if (!refs.length) {
        root.appendChild(el("p", { class: "bx--type-body-short-01" }, "No references yet. Capture one from a camera above."));
        return;
      }
      refs.forEach((r) => {
        const card = el("div", { class: "ref-card" },
          el("img", { class: "ref-card__img", src: r.image_url, alt: r.name }),
          el("div", { class: "ref-card__body" },
            el("h3", { class: "ref-card__title" }, r.name),
            el("div", { class: "ref-card__meta" },
              `id: ${r.id} • cam: ${r.camera_id} • bboxes: ${r.bbox_count} • ${r.width}×${r.height}`
            )
          ),
          el("div", { class: "ref-card__actions" },
            el("a", {
              class: "bx--btn bx--btn--tertiary bx--btn--sm",
              href: `/references/${encodeURIComponent(r.id)}/edit`,
            }, "Edit boxes"),
            el("button", {
              class: "bx--btn bx--btn--danger--ghost bx--btn--sm",
              type: "button",
              "data-id": r.id,
            }, "Delete"),
          )
        );
        card.querySelector("button").addEventListener("click", () => {
          if (!confirm(`Delete reference "${r.name}"?`)) return;
          window.App.api(`/api/references/${encodeURIComponent(r.id)}`, { method: "DELETE" })
            .then(() => loadReferences())
            .catch((e) => window.App.toast({ title: "Delete failed", body: e.message, kind: "error" }));
        });
        root.appendChild(card);
      });
    });
  }

  function capture() {
    const cam = document.getElementById("capture-camera").value;
    const name = document.getElementById("capture-name").value || undefined;
    return window.App.api("/api/references/capture", {
      method: "POST", body: { camera_id: cam, name },
    })
      .then((data) => {
        window.App.toast({ title: "Reference captured", body: "Now draw bounding boxes.", kind: "success" });
        loadReferences().then(() => {
          // Jump straight to the editor for the new ref.
          window.location.href = `/references/${encodeURIComponent(data.reference.id)}/edit`;
        });
      })
      .catch((e) => window.App.toast({ title: "Capture failed", body: e.message, kind: "error" }));
  }

  document.addEventListener("DOMContentLoaded", () => {
    loadCameras();
    loadReferences();
    document.getElementById("capture-btn").addEventListener("click", capture);
    document.getElementById("refresh-btn").addEventListener("click", loadReferences);
  });
})();
