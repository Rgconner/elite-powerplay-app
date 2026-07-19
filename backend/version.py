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
"""

BACKEND_VERSION      = "1.0.0"
BACKEND_RELEASE_DATE = "2025-07-11T00:00:00Z"
