# UI design (IBM Carbon)

The Visual Inspector operator UI follows the **IBM Design Language**,
implemented via the [Carbon Design System](https://carbondesignsystem.com).
We use Carbon's **CSS-only distribution** (`@carbon/styles` via the
IBM CDN) plus a small per-page CSS layer for custom chrome like the
bounding-box canvas. No Node toolchain, no React, no build step.

## Why Carbon

* **Proven in industrial UIs.** Carbon was designed for IBM's
  operator-facing products (Cloud, Watson, Maximo) — dense data
  tables, dark + light themes, and high-contrast focus states out
  of the box.
* **Excellent dark theme (`g100`).** Operators run these screens for
  hours; a properly-tuned dark theme with the right Gray ramp
  (Gray 100 → Gray 10) is much easier on the eyes than the default
  white Bootstrap look.
* **Token-driven.** Spacing (8-px scale), colour, type, motion are
  all design tokens. We consume them via CSS variables (`--cds-*`).
* **No JS components required for our use case.** Carbon's JS
  components handle complex widgets (data table sort, combobox
  filtering, etc.). Our UI is mostly forms + tables + the bbox
  canvas, all of which Carbon styles perfectly via the CSS-only
  build.

## What we use

* **Top app bar** (`bx--header`) with the Visual Inspector brand,
  primary nav, and a theme toggle in the right rail.
* **Tiles** (`bx--tile`) as the primary layout primitive — one tile
  per "section" of a page (Pin State, Recent Alerts, System, etc.).
* **Data table** (`bx--data-table`) for all tabular data: triggers,
  jobs, alerts, recent inspections.
* **Form fields** (`bx--text-input`, `bx--select-input`, `bx--number`,
  `bx--toggle`, `bx--text-area`) for the trigger / job / settings
  forms.
* **Buttons** (`bx--btn`) in `primary`, `tertiary`, `danger--tertiary`,
  `warning--tertiary`, `danger--ghost`, `ghost` variants to convey
  intent. The three alert verdict buttons use those three variants:
  Valid (primary), False positive (danger--tertiary), False negative
  (warning--tertiary).
* **Inline notification** (`bx--inline-notification`) reserved for
  non-toast errors on form pages.

## Theme

* The default theme is **Carbon `g100`** (dark, recommended for
  operator screens).
* A light theme (**Carbon `white`**) is also available. The user
  toggles between them with the **Theme** button in the header.
* The choice persists in `localStorage` and is sent to the server
  via `PUT /api/settings` so the next page load uses the same theme.
* Server-side, the active theme is stored in the `settings` row and
  in `app.theme` in the JSON config; new browser sessions read the
  value and pick the right Carbon stylesheet as `disabled`.

## Layout

* A 12-column **CSS Grid** is the base; we use a 1-, 2- or 3-column
  grid per page section.
* The bounding-box editor uses a 2-column grid: image on the left,
  box list on the right. Both panes are Carbon tiles.
* All spacing follows Carbon's 8-px scale (`8, 16, 24, 32, 40, 48, 64, 80`).
  Custom CSS uses these values; no off-grid magic numbers.

## Type

* **IBM Plex Sans** is loaded from the Google Fonts CDN as a
  pragmatic fallback for Carbon's own Plex CDN. Weights 300, 400,
  500, 600 are imported.
* Display headings use `bx--type-display-01` (page title) and
  `bx--type-productive-heading-03` (section headings).
* Body copy uses `bx--type-body-short-02` (subtitles) and
  `bx--type-body-short-01` (default body).
* Code / monospaced values (pin numbers, scores, paths) use
  `IBM Plex Mono` with a fallback chain of `Menlo, Consolas, monospace`.

## Colour tokens

The application uses Carbon's standard palette:

| Token              | Light theme | Dark theme (g100) | Used for                       |
| ------------------ | ----------- | ----------------- | ------------------------------ |
| `background`       | `#ffffff`   | `#161616`         | Page background                |
| `layer-01`         | `#f4f4f4`   | `#262626`         | Header, toast surface          |
| `layer-02`         | `#ffffff`   | `#262626`         | Inner tile surface             |
| `border-subtle-01` | `#e0e0e0`   | `#393939`         | Tile borders, hairlines        |
| `text-primary`     | `#161616`   | `#f4f4f4`         | Body text                      |
| `text-helper`      | `#6f6f6f`   | `#c6c6c6`         | Captions, labels               |
| `support-error`    | `#da1e28`   | `#fa4d56`         | Alert "Fail", False negative   |
| `support-warning`  | `#f1c21b`   | `#f1c21b`         | Alert verdict pending          |
| `support-success`  | `#198038`   | `#42be65`         | Alert "Pass", False positive   |
| `focus`            | `#0f62fe`   | `#0f62fe`         | 2-px focus outline             |

## Bounding-box editor (custom canvas)

The bbox editor is the only "non-Carbon" surface. We use a
`<canvas>` element wrapped in a Carbon tile with a Carbon-style
toolbar (Carbon buttons + a hint label). Our own `bbox_editor.js`
handles all drawing, drag, resize, and selection logic.

The canvas is drawn with:

* Green (`#42be65`) box outline for unselected boxes.
* Blue (`#0f62fe`) outline + 8-px corner / edge handles for the
  selected box.
* Dashed yellow (`#f1c21b`) preview while drawing a new box.
* A small label drawn in the top-left of each box (the user-supplied
  label from the side panel).

## Live data

* All real-time updates come over **Socket.IO** (`pin_state`,
  `alert_new`, `alert_resolved`, `inspection_complete`,
  `threshold_changed`, `visual_flash`, `notification`).
* The fallback for browsers that can't reach the Socket.IO endpoint
  is HTTP polling on `/api/pins` and `/api/alerts` every 3 s
  (implemented in `pin_dashboard.js` and `alerts.js`).

## Adding new pages

1. Create a Jinja template that extends `web/templates/base.html`.
2. Add a route in `src/visinsp/api/routes/pages.py` (or a new
   blueprint there).
3. If the page needs data, add a JSON endpoint in a new file under
   `src/visinsp/api/routes/`.
4. Add a small JS module under `web/static/js/` using the helpers
   exposed by `app.js` (`App.api`, `App.toast`, `App.flash`,
   `App.subscribe`).
5. If you need new Carbon components, look them up in
   [the Carbon site](https://carbondesignsystem.com/components/) and
   use the documented class names.
