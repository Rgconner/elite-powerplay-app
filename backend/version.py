"""
Backend version manifest.

HOW TO INCREMENT:
  1. Bump BACKEND_VERSION following semver (major.minor.patch).
  2. Update BACKEND_RELEASE_DATE to the current UTC date-time (ISO 8601).
  3. Commit the change — the date stamp is the canonical release time.

Version history:
  1.0.0  2025-07-11  Initial versioned release — full feature set:
                     FastAPI backend, PostgreSQL, APScheduler Spansh ingest,
                     PP scoring engine (fortify urgency + expand anchor proximity),
                     Target Analysis, Contested detection, public ingest-status
                     and version endpoints, JWT admin auth, change-password,
                     configurable scoring weights persisted in AdminSetting table.
  1.1.0  2025-07-11  Contested systems rewrite: new GET /api/powers/{name}/contested
                     endpoint queries power_state='Contested' directly from Spansh
                     data. New ContestedSystemInfo schema (no scoring). Removed
                     broken subquery that incorrectly used pp_system_snapshots.power
                     (controller field) to detect attacker presence.
  1.2.0  2025-07-11  Fix Contested ingestion gap: Spansh controlling_power filter
                    never returns Contested systems. Added second ingest pass using
                    power_state='Contested' filter to capture them. Fix CI: removed
                    cache-dependency-path that crashed when package-lock.json absent.
  1.3.0  2025-07-12  True contested detection rewrite: Spansh has no 'Contested'
                    power_state — contested systems are Unoccupied systems whose
                    power[] array contains 2+ entries. Added powers_list and
                    conflict_progress columns to pp_system_snapshots with ALTER TABLE
                    IF NOT EXISTS migration. Ingestion second pass now queries
                    power_state=Unoccupied and stores multi-power systems as internal
                    'Contested' label with full power list and conflict progress JSON.
                    /contested endpoint filters by powers_list ILIKE. Frontend
                    ContestedRow displays per-power progress bars with colour coding.
"""

BACKEND_VERSION      = "1.3.0"
BACKEND_RELEASE_DATE = "2025-07-12T00:00:00Z"
