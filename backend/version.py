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
  1.4.0  2025-07-12  Stale data fix: store spansh_updated_at from Spansh API
                    updated_at field. All live queries now filter out snapshots
                    where spansh_updated_at > 24h old — prevents resolved systems
                    like HUMA from appearing as contested. NULL spansh_updated_at
                    (pre-migration rows) pass through for graceful degradation.
                    Added index on spansh_updated_at. Data Age column added to
                    contested table with amber ⚠ warning for stale rows.
                    formatDataAge() / isStale() helpers added to contested.ts.
   1.5.0  2025-07-12  Stale filter hardened: NULL spansh_updated_at rows now also
                    gated on snapshot_time < 48h so pre-migration rows age out.
                    get_latest_snapshots() in scoring.py now applies the same
                    24h/48h staleness gate — fortify/expand recommendations no
                    longer use stale data. RST 1153 min-merits filter fixed:
                    was checking nonexistent merits_needed field; now correctly
                    uses merits_to_upgrade from RecommendationItem. Expand
                    Filters distance sliders removed from Table page; only the
                    'Within merits of acquire' slider remains with tooltip.
                    expandFortDist/expandShDist removed from FilterSettings.
   1.6.0  2025-07-12  Expand eligibility refactor:
                     - Unoccupied gate fixed: was `power_state != "Unoccupied" AND
                       current_power` (wrong — passed systems with no snapshot).
                       Now simply `if power_state != "Unoccupied": continue`.
                     - Stale bypass fixed: `snapshots.get(system.id, {})` returned
                       empty dict for systems with no fresh data, letting them pass
                       the Unoccupied check. Now `None` check before any field read.
                     - Frontend merit filter inverted: was `meritsLeft <= 120k-N`
                       (showed FAR systems). Fixed to `meritsLeft <= N` (shows
                       systems with ≤ N merits remaining — closest to acquisition).
                     - Slider label updated: 'Merits left to acquire ≤'
                     - Added /api/powers/{name}/expand-debug endpoint for verification.
   1.7.0  2026-06-27  Contested Target logic overhauled (spec-correct):
                     - /target-analysis: replaced U>R heuristic with real Contested
                       query (power_state='Contested', attacker in powers_list,
                       progress>0 in conflict_progress, stale filter).
                     - /contested: added conflict_progress>0 gate for selected power.
                     - isStale(): null-timestamp behaviour controlled by
                       contested_null_ts_is_stale admin setting.
                     - Admin panel: Staleness Settings card with toggle checkbox.
                     - Expansion state systems now included in expand scoring;
                       anchor proximity check skipped for Expansion state.
                     - RecommendationItem: conflict_progress field added.
                     - Expansion Targets: per-power conflict bars + ranking pill
                       (#N% lead, combined %), sorted maxProgress then sumProgress.
                     - Expand filter: 'Min lead progress %' replaces merit slider.
                     - Contested list: hard gates — max progress >= 100% AND
                       selected power present in conflict_progress.
                     - Admin settings TypeScript type fix in saveSettings payload.
"""

BACKEND_VERSION      = "1.7.0"
BACKEND_RELEASE_DATE = "2026-06-27T00:00:00Z"
