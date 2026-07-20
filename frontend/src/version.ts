/**
 * Frontend version manifest.
 *
 * HOW TO INCREMENT:
 *   1. Bump FRONTEND_VERSION following semver (major.minor.patch).
 *   2. Update FRONTEND_RELEASE_DATE to the current UTC date-time (ISO 8601).
 *   3. Commit the change — the date stamp is the canonical release time.
 *
 * Version history:
 *   1.0.0  2025-07-11  Initial versioned release — full feature set:
 *                      PP scoring engine, Table/2D/3D views, Recommendations panel,
 *                      Target Analysis, Contested Systems, Cycle Clock, Spansh status,
 *                      Expand anchor scoring (Fortified/Stronghold proximity model),
 *                      Admin panel with scoring weights, thresholds, change-password.
 *   1.1.0  2025-07-11  Contested systems rewrite: dedicated /contested endpoint,
 *                      ContestedSystemInfo type (no score), direct power_state='Contested'
 *                      query. RecommendationPanel and TableView updated to use new API.
 *   1.2.0  2025-07-11  Fix CI: removed cache-dependency-path crashing on absent
 *                      lockfile. Backend ingestion fix: Contested systems now
 *                      fetched via separate power_state filter pass.
 *   1.3.0  2025-07-12  True contested detection: Spansh has no Contested state.
 *                      Multi-power Unoccupied systems are now correctly identified.
 *                      ContestedSystemInfo extended with powers_list & conflict_progress.
 *                      ContestedRow shows per-power coloured progress bars.
 *                      Removed unused pct variable / void pct lint issue.
 *   1.5.0  2025-07-12  Stale data fix: spansh_updated_at surfaced from API.
 *                      All live queries filter spansh_updated_at > 24h old.
 *                      Contested table: Data Age column, ⚠ amber stale warning.
 *                      formatDataAge() / isStale() helpers added to contested.ts.
 *   1.6.0  2025-07-12  Expand eligibility refactor: correct Unoccupied gate,
 *                      stale-bypass fix, merit filter direction corrected.
 *                      Slider relabeled 'Merits left to acquire ≤'.
 *   1.7.0  2026-06-27  Contested Target logic overhauled (spec-correct):
 *                      power_state='Contested' gate, conflict_progress>0 check,
 *                      stale filter via admin toggle (contested_null_ts_is_stale).
 *                      Expansion state systems included in expand scoring.
 *                      Expansion Targets reworked: per-power conflict bars,
 *                      ranking pill (#N% lead), sort by maxProgress then
 *                      sumProgress. Expand filter changed to 'Min lead progress %'.
 *                      Contested list: acquisition gate (max>=100%) + selected
 *                      power present filter. Admin: Staleness Settings card.
 */

export const FRONTEND_VERSION      = "1.7.0";
export const FRONTEND_RELEASE_DATE = "2026-06-27T00:00:00Z";
