# Telemetry & Feed Health Plan

## Top-Level Overview

**Goal:** Add comprehensive operational telemetry for all four data feeds (Spansh batch ingest, EDSM sync, Spansh enrichment, and the EDDN real-time stream) so that the health, throughput, and freshness of each feed is visible at a glance.

**Approach:**
- Extend the `IngestionRun` database model with richer metrics fields (duration, error counts, API call counts) so telemetry persists across restarts.
- Instrument each backend service to record detailed per-run metrics into the database.
- Extend the EDDN listener to write a persistent heartbeat/stats record to the database that the backend can query.
- Add a new `/api/telemetry` backend endpoint that aggregates feed health into a single structured response.
- Add a stoplight status strip to the existing **Admin page** (no auth bypass — only visible when logged in) so feed health is visible at a glance.
- Add a new **Telemetry page** accessible from the main tab bar with a full operational dashboard: feed health panels, ingestion history, EDDN event rate sparklines, and enrichment cache stats.

**What this is NOT:**
- No Prometheus, OpenTelemetry, or external APM stack — all data stored in existing PostgreSQL.
- No frontend analytics / user tracking.
- No changes to business logic or scoring.

---

## Sub-Tasks

---

### Sub-Task 1 — Extend `IngestionRun` model with telemetry fields

**Intent:** The existing `ingestion_runs` table tracks only `records_processed` and `status`. To give meaningful feed health data we need duration, error counts, and API-level stats persisted in the DB so they survive restarts.

**Expected Outcomes:**
- `ingestion_runs` has new nullable columns: `duration_seconds`, `error_count`, `api_calls_made`, `api_errors`, `error_detail` (text).
- An Alembic migration (or `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE IF NOT EXISTS` applied at startup via `Base.metadata.create_all`) adds these columns.
- Existing rows are unaffected (all new columns are nullable with defaults).

**Todo List:**
1. In [`backend/models/models.py`](backend/models/models.py) add columns to `IngestionRun`: `duration_seconds` (Float, nullable), `error_count` (Integer, default 0), `api_calls_made` (Integer, default 0), `api_errors` (Integer, default 0), `error_detail` (String(2048), nullable).
2. Update [`backend/models/schemas.py`](backend/models/schemas.py) `IngestionRunSchema` to expose the new fields.
3. In [`backend/main.py`](backend/main.py) startup lifespan, after `Base.metadata.create_all(...)`, execute a one-time idempotent `ALTER TABLE ingestion_runs ADD COLUMN IF NOT EXISTS …` block via `engine.connect()` for each new column. This is safe to run on every startup (Postgres `IF NOT EXISTS` is a no-op if the column already exists).

**Relevant Context:**
- [`backend/models/models.py:37-49`](backend/models/models.py) — `IngestionRun` class
- [`backend/models/schemas.py`](backend/models/schemas.py) — Pydantic schemas
- Project uses `Base.metadata.create_all` at startup in [`backend/main.py`](backend/main.py) lifespan handler

**Status:** [x] done

---

### Sub-Task 2 — Add an `EddnFeedStats` persistent table

**Intent:** The EDDN listener is a separate process (`eddn-listener/`). The backend has no way to query how the live stream is performing without this shared table. A small `eddn_feed_stats` table acts as a heartbeat + rolling stats record that the EDDN listener writes and the backend reads.

**Expected Outcomes:**
- New `eddn_feed_stats` table with columns: `id` (primary key), `recorded_at` (DateTime), `events_total` (BigInteger), `events_last_hour` (Integer), `events_last_10min` (Integer), `dedup_rejected` (Integer), `last_event_ts` (DateTime, nullable), `listener_started_at` (DateTime).
- EDDN listener upserts a single row (or appends rolling rows) on each flush interval (already does 60s accumulation).
- Backend can query the latest row from this table for feed health.

**Todo List:**
1. In [`backend/models/models.py`](backend/models/models.py) add `EddnFeedStats` ORM class mapped to `eddn_feed_stats`.
2. In [`eddn-listener/`](eddn-listener/) find the accumulation flush loop and add a DB upsert of `Eddn FeedStats` at each flush (or at most every 60 s).
3. Ensure the eddn-listener shares the same `DATABASE_URL` env var (it likely already does via `docker-compose.yml`).
4. Update `Base.metadata.create_all` / migration so the table is created.

**Relevant Context:**
- [`eddn-listener/`](eddn-listener/) — separate service; explore its structure before implementing
- [`backend/services/realtime_accumulator.py`](backend/services/realtime_accumulator.py) — already reads `pp_powerplay_events` which the listener writes; same DB connection pattern applies
- [`docker-compose.yml`](docker-compose.yml) — confirm shared DB env var

**Status:** [x] done

---

### Sub-Task 3 — Instrument Spansh ingest service with detailed metrics

**Intent:** The Spansh ingest already logs record counts but doesn't persist API call stats, error counts, or duration. Instrumenting it gives us the data needed for the telemetry dashboard.

**Expected Outcomes:**
- `IngestionRun` rows for `source="spansh_pp"` are populated with `duration_seconds`, `error_count`, `api_calls_made`, `api_errors` after each run.
- Per-power page counts are summarised (not stored per-power; total API calls = pages × 1 is sufficient).
- Failed API calls increment `api_errors` and append to `error_detail` (truncated at 2 KB).

**Todo List:**
1. In [`backend/services/ingestion.py`](backend/services/ingestion.py) add a local counter dict at the top of `run_spansh_ingest`: `metrics = {"api_calls": 0, "api_errors": 0, "errors": []}`.
2. Wrap each `requests.post()` call to increment `metrics["api_calls"]`; catch HTTP errors / timeouts and increment `metrics["api_errors"]`, append truncated error message to `metrics["errors"]`.
3. On run completion (both success and failure paths) write `run.duration_seconds`, `run.api_calls_made`, `run.api_errors`, `run.error_count`, `run.error_detail` to the `IngestionRun` row before the final `db.commit()`.
4. In [`backend/routers/admin.py`](backend/routers/admin.py) `run_spansh_ingest_task` wrapper — ensure the `IngestionRun` `error_detail` is set on exception path too (it already catches and logs; add DB write).

**Relevant Context:**
- [`backend/services/ingestion.py:87-400`](backend/services/ingestion.py) — main ingest loop
- [`backend/routers/admin.py:89-113`](backend/routers/admin.py) — task wrapper that catches exceptions
- New `IngestionRun` fields from Sub-Task 1

**Status:** [x] done

---

### Sub-Task 4 — Instrument EDSM sync service with detailed metrics

**Intent:** Same as Sub-Task 3 but for the EDSM sync service. EDSM is rate-limited (1 req/sec) and the most failure-prone feed — tracking its API errors and rate-limit hits is high value.

**Expected Outcomes:**
- `IngestionRun` rows for `source="edsm"` are populated with `duration_seconds`, `error_count`, `api_calls_made`, `api_errors` after each run.
- Rate-limit hits (HTTP 429) are counted separately in `api_errors`.

**Todo List:**
1. In [`backend/services/edsm_sync.py`](backend/services/edsm_sync.py) add same `metrics` dict pattern as Sub-Task 3.
2. Wrap `_fetch_system_data()` HTTP calls to count `api_calls`, catch `httpx.TimeoutException` and HTTP 4xx/5xx, increment `api_errors`.
3. On run completion, write metrics to the `IngestionRun` row.

**Relevant Context:**
- [`backend/services/edsm_sync.py:46-126`](backend/services/edsm_sync.py) — sync loop
- `_HTTP_TIMEOUT = 10.0` already set; catch `httpx.TimeoutException` explicitly

**Status:** [x] done

---

### Sub-Task 5 — Instrument Spansh enrichment with cache hit/miss metrics

**Intent:** Spansh enrichment is on-demand and cached. We need a lightweight way to track cache hits, misses, and API errors without adding a new table — use an `AdminSetting`-style key/value store or a new small stats table.

**Recommendation:** Use a dedicated `enrichment_stats` table (appended per batch request) rather than AdminSetting (which is for config, not metrics). A single row per day with upsert-by-date keeps the table small.

**Expected Outcomes:**
- `enrichment_stats` table with columns: `date` (Date, primary key), `cache_hits` (Integer), `cache_misses` (Integer), `api_calls` (Integer), `api_errors` (Integer), `avg_fetch_ms` (Float).
- Each call to the batch enrichment endpoint increments the relevant counters for today's row.
- The `/api/telemetry` endpoint returns today's enrichment stats plus the `SpanshEnrichment` cache size (already tracked via `/api/spansh/enrich-status`).

**Todo List:**
1. In [`backend/models/models.py`](backend/models/models.py) add `EnrichmentStats` ORM class mapped to `enrichment_stats` (date PK, daily counters).
2. In [`backend/routers/spansh.py`](backend/routers/spansh.py) batch enrichment handler — after each cache lookup and each API call, atomically increment today's `EnrichmentStats` row (UPSERT by date).
3. Update `Base.metadata.create_all` / migration for the new table.

**Relevant Context:**
- [`backend/routers/spansh.py:348-430`](backend/routers/spansh.py) — batch enrichment with fallback cache logic
- Existing `SpanshEnrichment` model (cached_at, has_platinum, etc.) already in DB; only needs counter overlay

**Status:** [x] done

---

### Sub-Task 6 — Add `/api/telemetry` backend endpoint

**Intent:** Aggregate all feed health data into a single structured JSON response that the frontend Telemetry page and Admin stoplight can consume. This endpoint is **JWT-gated** (requires admin auth) — the same `AdminUserDep` dependency used throughout `admin.py`.

**Expected Outcomes:**
- `GET /api/telemetry` returns a JSON object with feed health for all four sources.
- Each feed section includes: `status` (green/yellow/red), `last_run_at`, `last_success_at`, `records_last_run`, `error_count_last_run`, `api_calls_last_run`, `api_errors_last_run`, `duration_seconds_last_run`, `next_run_at` (where applicable).
- EDDN section includes: `last_event_ts`, `events_last_hour`, `events_last_10min`, `dedup_rejected`, `listener_uptime_seconds`.
- Enrichment section includes: today's `cache_hits`, `cache_misses`, `api_calls`, `api_errors`, `total_cached` (from existing `SpanshEnrichment` count).
- Status logic: **green** = last run succeeded < 2× scheduled interval ago; **yellow** = last run succeeded but > 2× interval or currently running; **red** = last run failed or no run in > 3× interval.
- EDDN **green** = event received in last 30 min; **yellow** = last event 30 min–2 hr ago; **red** = no event in 2+ hours.

**Todo List:**
1. Create [`backend/routers/telemetry.py`](backend/routers/telemetry.py) with a `GET /telemetry` route protected by `AdminUserDep`.
2. Query: last `IngestionRun` for `spansh_pp`, last `IngestionRun` for `edsm`, latest `EddnFeedStats` row, today's `EnrichmentStats` row, existing enrichment cache count.
3. Compute status color for each feed using the rules above.
4. Register the new router in [`backend/main.py`](backend/main.py) under prefix `/telemetry`.
5. Add `TelemetryRouter` import to main and append to `app.include_router()` calls.

**Relevant Context:**
- [`backend/routers/admin.py:116-143`](backend/routers/admin.py) — existing JWT-gated `/status` and `/health` pattern to follow (uses `AdminUserDep`)
- [`backend/main.py:205-238`](backend/main.py) — router registration pattern
- New models from Sub-Tasks 1–5

**Status:** [x] done

---

### Sub-Task 7 — Add Admin page stoplight strip

**Intent:** The Admin page is the operator's home. A compact row of four coloured indicator dots (one per feed) with a label and last-updated timestamp gives instant situational awareness without requiring navigation to the Telemetry page. Visible only when logged in (uses existing auth state).

**Expected Outcomes:**
- A "Feed Health" section near the top of the logged-in Admin view (above ingest controls).
- Four stoplight indicators: `EDDN Stream`, `Spansh Ingest`, `EDSM Sync`, `Enrichment Cache`.
- Each shows: coloured dot (green/yellow/red), feed name, last event or last run timestamp as a relative time ("3m ago", "2h ago"), and a brief status label ("OK", "Stale", "Failed").
- Data fetched from the new `/api/telemetry` endpoint on page load (added to the existing `Promise.all` in `loadData()`).
- No new auth requirement — already gated by admin login in `AdminPage.tsx`.

**Todo List:**
1. In [`frontend/src/pages/AdminPage.tsx`](frontend/src/pages/AdminPage.tsx) add a `TelemetryStatus` TypeScript interface matching the `/api/telemetry` response shape.
2. Add `telemetryStatus` state field and fetch it in the existing `loadData()` `Promise.all`.
3. Add a `FeedStoplight` functional component (inline in the file) that renders a row of four pill indicators with colour from status field.
4. Render `<FeedStoplight>` near the top of the logged-in view, above the ingest trigger buttons.

**Relevant Context:**
- [`frontend/src/pages/AdminPage.tsx:224-257`](frontend/src/pages/AdminPage.tsx) — `loadData()` with `Promise.all` pattern
- [`frontend/src/pages/AdminPage.tsx:159-166`](frontend/src/pages/AdminPage.tsx) — existing `StatusBadge` component pattern to reuse for stoplight dots
- Dark theme: background `#0d1117`, border `#30363d`, accent `#58a6ff`

**Status:** [x] done

---

### Sub-Task 8 — Add Telemetry page to frontend

**Intent:** A dedicated Telemetry page gives the full operational dashboard: all four feed panels with history, EDDN event rate, enrichment cache stats, and raw ingestion run history. It lives in the main tab bar but mirrors the Admin page auth gate — if the user is not logged in, it shows a login prompt (or redirects to Admin login). This avoids duplicating an entirely separate auth system.

**Expected Outcomes:**
- New `TelemetryPage.tsx` in `frontend/src/pages/` with four feed panels laid out in a 2×2 grid on desktop.
- Each panel shows: feed name, stoplight status, last run details (timestamp, duration, records, errors), and a mini history table of the last 5 runs (for batch feeds) or a rolling event-rate display (for EDDN).
- EDDN panel: last event timestamp, events/hr (last hour), events/10min, dedup rejected count.
- Enrichment panel: total cached, today's cache hits vs misses, hit rate %, API errors today.
- Refresh button that re-fetches `/api/telemetry` on demand.
- Auto-refresh every 60 seconds.
- In [`frontend/src/App.tsx`](frontend/src/App.tsx): add a `telemetry` tab to the tab bar (e.g. "📡 Telemetry") with the same tab styling as existing tabs. The tab is always visible; the page itself shows a login wall if no admin token is present.

**Todo List:**
1. Create [`frontend/src/pages/TelemetryPage.tsx`](frontend/src/pages/TelemetryPage.tsx) — no external dependencies, uses `fetch` with `getAuthHeader()` against `/api/telemetry`. If no token present (HTTP 401), render a "Please log in via Admin panel" message.
2. Define TypeScript interfaces for the telemetry response in a shared location or inline (consistent with Sub-Task 7 types).
3. Implement four feed panels as functional components within the file.
4. Add `useEffect` with 60-second auto-refresh interval.
5. In [`frontend/src/App.tsx`](frontend/src/App.tsx) add `"telemetry"` to the `Tab` union, add it to `TAB_LABELS`, add `{tab === "telemetry" && <TelemetryPage />}` to the render section.
6. Import `TelemetryPage` at the top of `App.tsx`.

**Relevant Context:**
- [`frontend/src/App.tsx:1-97`](frontend/src/App.tsx) — tab bar pattern; add telemetry as a 4th tab
- [`frontend/src/pages/AdminPage.tsx:159-166`](frontend/src/pages/AdminPage.tsx) — `StatusBadge` pattern for visual reference
- Dark-mode colour palette: background `#0d1117`, card `#161b22`, border `#30363d`, text `#e6edf3`, muted `#8b949e`
- No router library used — tabs controlled by `useState` in `App.tsx`

**Status:** [x] done

---

## Recommendations & Notes

### Data freshness thresholds (configurable)
Stoplight thresholds are hardcoded in the telemetry router for now. If they need tuning without a redeploy, add keys to `admin_settings` (e.g. `telemetry_eddn_stale_minutes`, `telemetry_spansh_stale_hours`) — but this is out of scope for this plan.

### EDDN listener — read before implementing Sub-Task 2
The implementor MUST read the `eddn-listener/` directory before starting Sub-Task 2 to understand the flush loop and DB connection pattern. The table DDL lives in `backend/models/models.py` (shared), but the INSERT/UPSERT code lives in the listener process.

### Migration strategy (confirmed)
- **New tables** (`eddn_feed_stats`, `enrichment_stats`): handled automatically by `Base.metadata.create_all` at startup.
- **New columns on `ingestion_runs`**: use `ALTER TABLE ingestion_runs ADD COLUMN IF NOT EXISTS …` executed via `engine.connect()` in the startup lifespan handler, immediately after `create_all`. Safe to run on every restart — Postgres no-ops if columns already exist.
- No Alembic needed.

### Auth approach (confirmed)
Both the `/api/telemetry` endpoint and the frontend Telemetry page require admin authentication. The page shows a login wall (not a redirect) if no token is present, consistent with how `AdminPage.tsx` behaves. The `getAuthHeader()` / `getAdminToken()` helpers in [`frontend/src/api/admin.ts`](frontend/src/api/admin.ts) should be reused directly.

### Sub-task ordering
Sub-Tasks 1–2 (models) must be completed before 3–5 (instrumentation) and before 6 (endpoint). Sub-Tasks 7 and 8 (frontend) depend on Sub-Task 6 (endpoint). All backend sub-tasks should be done before frontend.

```
[1] Extend IngestionRun model
[2] Add EddnFeedStats table
      ↓
[3] Instrument Spansh ingest     [4] Instrument EDSM sync     [5] Instrument enrichment
      ↓                                 ↓                           ↓
[6] /api/telemetry endpoint
      ↓
[7] Admin stoplight strip        [8] Telemetry page
```
