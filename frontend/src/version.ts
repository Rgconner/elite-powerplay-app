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
 */

export const FRONTEND_VERSION      = "1.1.0";
export const FRONTEND_RELEASE_DATE = "2025-07-11T12:00:00Z";
