# Elite Powerplay App — Code Improvement Plan

## Top-Level Overview

The Elite Powerplay App is a well-architected, full-stack application (React/TypeScript frontend, Python/FastAPI backend) used for analysing Elite Dangerous power-play data. The codebase has strong fundamentals: dual DB connection pools, dependency injection, type-safe contracts, and good documentation.

This plan addresses the meaningful gaps found in the review, organised by priority. The goal is to improve security, reliability, maintainability, and user experience without introducing unnecessary abstractions or rewrites.

**Scope**: Security hardening, error handling consistency, input validation, audit logging, scoring constants, admin job feedback, and test scaffolding.

**Non-goals**: Full rewrites, major architectural changes, adding new features, or performance optimisations (caching, pagination) unless they address a concrete bug.

---

## Sub-Tasks

---

### Sub-Task 1 — Fix CORS Configuration

**Status**: `[x] done`

**Intent**  
The backend uses `allow_origins=["*"]` with `allow_credentials=True`, which is both a browser security error (browsers block credentialed wildcard CORS) and a policy risk. Restrict CORS to environment-configured origins and narrow the allowed methods and headers.

**Expected Outcomes**
- `CORS_ORIGINS` environment variable controls allowed origins
- `allow_methods` limited to `["GET", "POST", "PATCH"]`
- `allow_headers` limited to `["Content-Type", "Authorization"]`
- Local dev continues to work with default value of `http://localhost:5173`

**Todo List**
1. In `backend/main.py`, read `CORS_ORIGINS` from the environment (comma-separated list, defaulting to `http://localhost:5173`)
2. Replace `allow_origins=["*"]` with the parsed list
3. Replace `allow_methods=["*"]` with `["GET", "POST", "PATCH"]`
4. Replace `allow_headers=["*"]` with `["Content-Type", "Authorization"]`
5. Add `CORS_ORIGINS` with an example value (`http://localhost:5173,https://ppa.snwbd.com`) to `backend/.env.example` (or the README env-var table)

**Relevant Context**
- `backend/main.py` lines ~191–197 (CORSMiddleware block)
- README env-var table for documentation

---

### Sub-Task 2 — Add Admin Settings Validation

**Status**: `[x] done`

**Intent**  
The admin `PATCH /settings` endpoint accepts arbitrary string values with no validation. An admin could accidentally set a scoring weight to a negative number or non-numeric string, silently breaking recommendations. Add Pydantic field validation to the `SettingUpdate` schema to enforce numeric ranges for known key types.

**Expected Outcomes**
- Setting keys ending in `_weight`, `_max`, or `_bonus` must be numeric and in the range `[0, 10000]`
- Setting keys ending in `_threshold` must be numeric and in the range `[0, 365]`
- Invalid values return HTTP 422 with a clear error message
- Valid values continue to be accepted unchanged

**Todo List**
1. In the Pydantic schema for `SettingUpdate` (in `backend/schemas/` or inline in `backend/routers/admin.py`), add a `field_validator` for `value` that inspects the `key` name and applies the appropriate numeric range check
2. Write a short inline comment explaining the key-name conventions used for validation

**Relevant Context**
- `backend/routers/admin.py` — `update_settings` endpoint and `SettingUpdate` model
- `backend/schemas/` — if SettingUpdate is defined there

---

### Sub-Task 3 — Add Audit Logging for Admin Actions

**Status**: `[x] done`

**Intent**  
Admin panel changes (settings updates, ingest triggers) are not audited. If something goes wrong it is impossible to know who changed what or when. Add a lightweight audit log that records admin email, action, resource key, old value, new value, and timestamp.

**Expected Outcomes**
- Every successful call to `PATCH /settings` writes one `AuditLog` row per changed key
- Every successful call to `POST /ingest/*` writes one `AuditLog` row recording who triggered the ingest
- `AuditLog` rows are persisted to the database (not just logged to console)
- A simple `GET /admin/audit` endpoint returns recent audit entries (admin-only)

**Todo List**
1. Add an `AuditLog` SQLAlchemy model to `backend/models/` with columns: `id`, `admin_email`, `action`, `resource_key`, `old_value`, `new_value`, `timestamp`
2. Create the table via an incremental migration in `backend/main.py` (consistent with existing pattern there)
3. In `update_settings`, capture the old value before overwriting, then insert an `AuditLog` row per changed key
4. In each `POST /ingest/*` endpoint, insert an `AuditLog` row recording the trigger action
5. Add a `GET /admin/audit` endpoint (admin-only) returning recent rows (limit 200, newest first)

**Relevant Context**
- `backend/models/` — existing SQLAlchemy model files
- `backend/main.py` — incremental migration pattern (search for `op.add_column` or similar)
- `backend/routers/admin.py` — `update_settings` and ingest trigger endpoints

---

### Sub-Task 4 — Centralise Scoring Magic Numbers

**Status**: `[x] done`

**Intent**  
The `computeTargetScore` function in the frontend uses hard-coded numeric weights (50, 30, 100, 20, 1000) with no explanation of what they represent. These should be named constants in a dedicated file so that their purpose is clear and they can be adjusted in one place.

**Expected Outcomes**
- A `SCORE_WEIGHTS` (or similar) constant object is defined with named keys: `PROGRESS_MAX`, `DISTANCE_MAX`, `DISTANCE_FALLOFF_LY`, `THREAT_MAX`, `THREAT_THRESHOLD_MERITS`
- `computeTargetScore` (and any other callers) reference the named constants instead of literals
- No behavioural change — values remain the same

**Todo List**
1. In `frontend/src/utils/scoring.ts` (or a new `frontend/src/constants/scoring.ts`), define the named constant object with the five weight values
2. Replace the numeric literals in `computeTargetScore` with the named constants
3. Add a one-line comment on each constant explaining what it controls

**Relevant Context**
- `frontend/src/utils/scoring.ts` — `computeTargetScore` function
- Existing constant pattern in the same file (e.g., `MERIT_ACQUIRE`, `MERIT_FORTIFIED`)

---

### Sub-Task 5 — Add Background Job Status Tracking

**Status**: `[x] done`

**Intent**  
Admin-triggered ingest endpoints return immediately with "started in background" but provide no way to check whether the job succeeded or failed. The admin has no feedback for potentially hour-long operations. Add a simple in-process job status store and a polling endpoint.

**Expected Outcomes**
- Each `POST /ingest/*` endpoint returns a `job_id` string
- A `GET /admin/ingest/status/{job_id}` endpoint returns `{status: "pending"|"running"|"completed"|"failed", error: string|null}`
- On failure, `error` contains the exception message
- Job entries expire after 24 hours (simple dict with timestamp, no external dependency)

**Todo List**
1. In `backend/routers/admin.py`, add a module-level `BACKGROUND_JOBS` dict (keyed by UUID string) storing `{status, error, started_at}`
2. Wrap each background ingest task in a closure that updates the job dict on start, completion, and failure
3. Update each `POST /ingest/*` endpoint to generate a `uuid4` job ID, register it, and return it in the response
4. Add `GET /admin/ingest/status/{job_id}` endpoint (admin-only)
5. Add a simple cleanup: at the start of each new ingest trigger, remove job entries older than 24 hours from the dict

**Relevant Context**
- `backend/routers/admin.py` — ingest trigger endpoints (`trigger_spansh_ingest`, etc.)
- No external dependency needed (in-memory dict is sufficient for a single-process deployment)

---

### Sub-Task 6 — Standardise Frontend Error Handling

**Status**: `[x] done`

**Intent**  
Several `.catch()` blocks in the frontend either swallow errors silently or show empty data without distinguishing between "no results" and "load failed". Introduce a small `ApiError` class and a `handleFetchError` utility so that all API calls throw consistent, typed errors, and components can surface a meaningful message to the user.

**Expected Outcomes**
- An `ApiError` class exists in `frontend/src/api/` with `statusCode`, `message`, and optional `detail`
- A `handleFetchError(res: Response): Promise<never>` helper parses the FastAPI error body and throws `ApiError`
- All existing API functions in `frontend/src/api/*.ts` use `handleFetchError` instead of ad-hoc inline checks
- At least the key data-fetching hooks in `TableView.tsx` and `TargetListView.tsx` set visible error state (not just `console.warn`) when a fetch fails

**Todo List**
1. Create `frontend/src/api/errors.ts` with the `ApiError` class and `handleFetchError` helper
2. Update `frontend/src/api/admin.ts` to use `handleFetchError`
3. Update `frontend/src/api/powers.ts` (and any other API files) to use `handleFetchError`
4. In `TableView.tsx`, replace silent `.catch(() => {})` and `.catch(() => setX([]))` blocks with proper error state; show a visible inline error message when a fetch fails
5. In `TargetListView.tsx`, do the same
6. No new UI component needed — a simple `<p className="error-text">` or existing alert styling is sufficient

**Relevant Context**
- `frontend/src/api/admin.ts` — current ad-hoc error extraction
- `frontend/src/api/powers.ts` — API fetch functions
- `frontend/src/pages/TableView.tsx` — lines with `.catch(() => {})` and `.catch(() => setX([]))`
- `frontend/src/pages/TargetListView.tsx` — similar patterns

---

### Sub-Task 7 — Add Test Scaffolding

**Status**: `[x] done`

**Intent**  
The codebase has zero tests. The highest-risk logic is the scoring and decay calculations in both the frontend and backend. This sub-task sets up the test infrastructure and writes a focused initial suite covering the pure calculation functions — not UI or database integration.

**Expected Outcomes**
- Frontend: Vitest configured; tests exist for `computeTargetScore` and related scoring utils in `frontend/src/utils/scoring.ts`
- Backend: pytest configured; tests exist for decay calculation logic in `backend/services/decay.py`
- Both test suites pass with `npm test` (frontend) and `pytest` (backend)
- No UI or database tests required at this stage

**Todo List**
1. In `frontend/`, install `vitest` and `@vitest/ui` as dev dependencies; add a `test` script to `package.json`; create `vite.config.ts` (or update it) with a `test` block
2. Create `frontend/src/utils/scoring.test.ts` with unit tests for `computeTargetScore` covering: zero progress, full progress, near vs. far distance, zero threat, max threat, combined score ceiling
3. In `backend/`, add `pytest` and `pytest-cov` to `requirements.txt` (or a new `requirements-dev.txt`)
4. Create `backend/tests/__init__.py` and `backend/tests/test_decay.py` with unit tests for the decay functions: boundary values (0%, 50%, 100% decay), edge cases (no reinforcement, full fortification)
5. Add a note to the README indicating how to run tests

**Relevant Context**
- `frontend/src/utils/scoring.ts` — the functions to test
- `backend/services/decay.py` — the functions to test
- Existing `vite.config.ts` — check for existing config to extend, not replace
- `frontend/package.json` — for adding the test script

---

## Excluded from Scope

The following were noted in the review but are deliberately excluded from this plan:

- **Pagination** on `/systems` endpoints — no evidence of performance problems in production; adds API breaking change
- **Redis caching** — adds infrastructure dependency without evidence of a current bottleneck  
- **Full a11y audit** — large scope; best handled as a dedicated effort
- **D3.js type fixes** — cosmetic TypeScript improvement; low risk, low value right now
- **CI/CD pipeline** — important but out of scope for a code-quality improvement pass

These can be addressed in follow-up plans.
