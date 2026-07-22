/*
 * Bounding-box editor — Canvas drawing + side panel of boxes.
 *
 * Modes:
 *   - idle:   click a box to select, drag handles to resize, drag body to move.
 *   - draw:   click and drag to add a new box.
 *
 * Boxes are stored in image coordinates; the canvas scales them with the
 * CSS-displayed size.
 */

(function () {
  "use strict";

  const REF_ID = window.VISINSP_REF_ID;
  const HANDLE = 8;
  const HANDLE_KIND = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

  const state = {
    ref: null,
    boxes: [],   // [{id, x, y, w, h, label, weight, _sel?}]
    img: null,    // HTMLImageElement
    scale: 1,     // canvas px / image px
    mode: "idle", // "idle" | "draw"
    drag: null,   // {kind, idx, handle?, startX, startY, origBox}
    selected: -1,
  };

  // ---- DOM helpers ----
  function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => {
      if (k === "class") e.className = v;
      else if (k.startsWith("data-")) e.setAttribute(k, v);
      else if (k === "value" || k === "checked" || k === "type" || k === "min" ||
               k === "max" || k === "step" || k === "placeholder" || k === "id" ||
               k === "rows" || k === "disabled") e.setAttribute(k, v);
      else e.setAttribute(k, v);
    });
    children.flat().forEach((c) => {
      if (c == null) return;
      if (typeof c === "string") e.appendChild(document.createTextNode(c));
      else e.appendChild(c);
    });
    return e;
  }

  // ---- box math ----
  function newBoxId() { return "bb_" + Math.random().toString(16).slice(2, 12); }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function normalize(x, y, w, h) {
    const x1 = Math.min(x, x + w), y1 = Math.min(y, y + h);
    const x2 = Math.max(x, x + w), y2 = Math.max(y, y + h);
    return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
  }
  function hitHandle(b, px, py) {
    const cs = [ [-1, -1], [0, -1], [1, -1], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0] ];
    for (let i = 0; i < cs.length; i++) {
      const dx = cs[i][0] * HANDLE, dy = cs[i][1] * HANDLE;
      if (Math.abs(px - (b.x + b.w / 2 + dx)) <= HANDLE &&
          Math.abs(py - (b.y + b.h / 2 + dy)) <= HANDLE) {
        return HANDLE_KIND[i];
      }
    }
    return null;
  }
  function hitBox(b, px, py) {
    return px >= b.x && px <= b.x + b.w && py >= b.y && py <= b.y + b.h;
  }
  function pointToImage(evt) {
    const c = document.getElementById("bbox-canvas");
    const r = c.getBoundingClientRect();
    const px = (evt.clientX - r.left) * (c.width / r.width);
    const py = (evt.clientY - r.top) * (c.height / r.height);
    return { x: px / state.scale, y: py / state.scale };
  }

  // ---- drawing ----
  function draw() {
    const c = document.getElementById("bbox-canvas");
    if (!c || !state.img) return;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#000"; ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(state.img, 0, 0, c.width, c.height);

    // boxes
    state.boxes.forEach((b, i) => {
      const x = b.x * state.scale, y = b.y * state.scale;
      const w = b.w * state.scale, h = b.h * state.scale;
      ctx.lineWidth = (i === state.selected) ? 3 : 2;
      ctx.strokeStyle = (i === state.selected) ? "#0f62fe" : "#42be65";
      ctx.strokeRect(x, y, w, h);
      // label
      if (b.label) {
        ctx.font = "12px IBM Plex Sans, sans-serif";
        ctx.fillStyle = (i === state.selected) ? "#0f62fe" : "#42be65";
        ctx.fillText(b.label, x + 4, y + 14);
      }
      // handles on the selected box
      if (i === state.selected) {
        const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
        const offsets = [[-1,-1],[0,-1],[1,-1],[1,0],[1,1],[0,1],[-1,1],[-1,0]];
        ctx.fillStyle = "#0f62fe";
        offsets.forEach(([dx, dy]) => {
          const hx = (cx + dx * b.w / 2) * state.scale - HANDLE / 2;
          const hy = (cy + dy * b.h / 2) * state.scale - HANDLE / 2;
          ctx.fillRect(hx, hy, HANDLE, HANDLE);
        });
      }
    });
    // active drag preview
    if (state.drag && state.drag.kind === "draw") {
      const n = normalize(state.drag.startX, state.drag.startY,
                         state.drag.curX - state.drag.startX,
                         state.drag.curY - state.drag.startY);
      ctx.strokeStyle = "#f1c21b";
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.strokeRect(n.x * state.scale, n.y * state.scale, n.w * state.scale, n.h * state.scale);
      ctx.setLineDash([]);
    }
  }

  // ---- events ----
  function onDown(evt) {
    if (!state.img) return;
    const p = pointToImage(evt);
    if (state.mode === "draw") {
      state.drag = { kind: "draw", startX: p.x, startY: p.y, curX: p.x, curY: p.y };
      return;
    }
    // select / drag existing box
    for (let i = state.boxes.length - 1; i >= 0; i--) {
      const b = state.boxes[i];
      const handle = hitHandle(b, p.x, p.y);
      if (handle) {
        state.selected = i;
        state.drag = { kind: "resize", idx: i, handle, startX: p.x, startY: p.y, orig: { ...b } };
        draw();
        return;
      }
    }
    for (let i = state.boxes.length - 1; i >= 0; i--) {
      if (hitBox(state.boxes[i], p.x, p.y)) {
        state.selected = i;
        state.drag = { kind: "move", idx: i, startX: p.x, startY: p.y, orig: { ...state.boxes[i] } };
        draw();
        renderList();
        return;
      }
    }
    state.selected = -1;
    draw();
    renderList();
  }
  function onMove(evt) {
    if (!state.drag) return;
    const p = pointToImage(evt);
    const d = state.drag;
    if (d.kind === "draw") {
      d.curX = p.x; d.curY = p.y;
      draw();
    } else if (d.kind === "move") {
      const b = state.boxes[d.idx];
      const dx = p.x - d.startX, dy = p.y - d.startY;
      b.x = clamp(d.orig.x + dx, 0, state.img.width  - b.w);
      b.y = clamp(d.orig.y + dy, 0, state.img.height - b.h);
      draw();
    } else if (d.kind === "resize") {
      const b = state.boxes[d.idx];
      const o = d.orig;
      let nx = o.x, ny = o.y, nw = o.w, nh = o.h;
      const right = o.x + o.w, bottom = o.y + o.h;
      if (d.handle.includes("w")) { nx = clamp(p.x, 0, right - 1);  nw = right - nx; }
      if (d.handle.includes("e")) { nw = clamp(p.x - o.x, 1, state.img.width - o.x); }
      if (d.handle.includes("n")) { ny = clamp(p.y, 0, bottom - 1); nh = bottom - ny; }
      if (d.handle.includes("s")) { nh = clamp(p.y - o.y, 1, state.img.height - o.y); }
      b.x = nx; b.y = ny; b.w = nw; b.h = nh;
      draw();
    }
  }
  function onUp() {
    if (!state.drag) return;
    if (state.drag.kind === "draw") {
      const n = normalize(state.drag.startX, state.drag.startY,
                         state.drag.curX - state.drag.startX,
                         state.drag.curY - state.drag.startY);
      if (n.w >= 4 && n.h >= 4) {
        const b = { id: newBoxId(), x: n.x, y: n.y, w: n.w, h: n.h, label: "", weight: 1.0 };
        state.boxes.push(b);
        state.selected = state.boxes.length - 1;
      }
      state.mode = "idle";
      setHint("Box added. Drag to move, drag handles to resize, or click + Add box.");
    }
    state.drag = null;
    draw();
    renderList();
  }

  // ---- side panel ----
  function renderList() {
    const ul = document.getElementById("bbox-list");
    if (!ul) return;
    ul.innerHTML = "";
    if (!state.boxes.length) {
      ul.appendChild(el("li", { class: "bx--type-helper-text-01" }, "No boxes yet."));
      return;
    }
    state.boxes.forEach((b, i) => {
      const li = el("li", { class: i === state.selected ? "selected" : "", "data-idx": i },
        el("input", { class: "bx--text-input", type: "text", placeholder: "label", value: b.label }),
        el("input", { class: "bx--text-input bx--number", type: "number", min: 0, max: state.img ? state.img.width : 9999, step: 1, value: Math.round(b.x) }),
        el("input", { class: "bx--text-input bx--number", type: "number", min: 0, max: state.img ? state.img.height : 9999, step: 1, value: Math.round(b.y) }),
        el("input", { class: "bx--text-input bx--number", type: "number", min: 1, step: 1, value: Math.round(b.w) }),
        el("input", { class: "bx--text-input bx--number", type: "number", min: 0, max: 10, step: 0.1, value: b.weight }),
      );
      li.addEventListener("click", (e) => {
        if (e.target.tagName === "INPUT") return;
        state.selected = i; draw(); renderList();
      });
      const inputs = li.querySelectorAll("input");
      inputs[0].addEventListener("input", (e) => { b.label = e.target.value; draw(); });
      inputs[1].addEventListener("input", (e) => { b.x = clamp(+e.target.value, 0, state.img.width - 1); draw(); });
      inputs[2].addEventListener("input", (e) => { b.y = clamp(+e.target.value, 0, state.img.height - 1); draw(); });
      inputs[3].addEventListener("input", (e) => { b.w = Math.max(1, +e.target.value); draw(); });
      inputs[4].addEventListener("input", (e) => { b.weight = Math.max(0, Math.min(10, +e.target.value)); draw(); });
      ul.appendChild(li);
    });
  }

  function setHint(text) {
    const h = document.getElementById("bbox-hint");
    if (h) h.textContent = text;
  }

  // ---- load + bind ----
  function loadRef() {
    window.App.api(`/api/references/${encodeURIComponent(REF_ID)}`).then((data) => {
      const ref = data.reference;
      state.ref = ref;
      state.boxes = (ref.bboxes || []).map((b) => ({ ...b }));
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        state.img = img;
        const c = document.getElementById("bbox-canvas");
        const maxW = Math.min(1280, c.parentElement.clientWidth - 4);
        const scale = Math.min(1, maxW / img.width);
        c.width  = Math.round(img.width  * scale);
        c.height = Math.round(img.height * scale);
        state.scale = c.width / img.width;
        draw();
        renderList();
        document.getElementById("ref-name").value = ref.name || "";
        document.getElementById("ref-notes").value = ref.notes || "";
      };
      img.onerror = () => {
        window.App.toast({ title: "Image load failed", body: ref.image_path, kind: "error" });
      };
      img.src = ref.image_url || `/refs/${(ref.image_path || "").split(/[\\/]/).pop()}`;
    }).catch((e) => window.App.toast({ title: "Reference load failed", body: e.message, kind: "error" }));
  }

  function save() {
    const body = {
      name: document.getElementById("ref-name").value,
      notes: document.getElementById("ref-notes").value,
      bboxes: state.boxes,
    };
    window.App.api(`/api/references/${encodeURIComponent(REF_ID)}`, {
      method: "PUT", body,
    }).then(() => {
      window.App.toast({ title: "Reference saved", kind: "success" });
    }).catch((e) => window.App.toast({ title: "Save failed", body: e.message, kind: "error" }));
  }

  document.addEventListener("DOMContentLoaded", () => {
    const c = document.getElementById("bbox-canvas");
    c.addEventListener("mousedown", onDown);
    c.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    c.addEventListener("touchstart", (e) => { if (e.touches[0]) onDown(e.touches[0]); });
    c.addEventListener("touchmove",  (e) => { if (e.touches[0]) onMove(e.touches[0]); });
    c.addEventListener("touchend",   onUp);

    document.getElementById("bbox-add").addEventListener("click", () => {
      state.mode = "draw";
      setHint("Drag on the image to draw a new box.");
    });
    document.getElementById("bbox-delete").addEventListener("click", () => {
      if (state.selected < 0) return;
      state.boxes.splice(state.selected, 1);
      state.selected = -1;
      draw(); renderList();
    });
    document.getElementById("save-btn").addEventListener("click", save);
    loadRef();
  });
})();
