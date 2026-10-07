# `backend/scripts/`

Operational, debug, and utility scripts that don't belong in the package
runtime. Moved out of the project root as part of the N-1 cleanup pass.

| Subdir | Purpose |
|---|---|
| `admin/` | One-time / infrequent operational scripts. `create_admin.py` is the canonical example — it bootstraps the first admin user against an existing database. |
| `debug/` | Ad-hoc investigation scripts kept for reference. They were used during development of the Spansh enrichment (PLAT / BOOM / PRIST) logic and the Spansh API probes. Most of them print to stdout and exit; they do not modify the database. Safe to delete if you no longer need the reference. |
| `util/` | Small standalone utilities (URL reachability, cache clearing, line counting). |

## Running a script

All scripts are run with plain Python from the project root. They expect
the backend dependencies to be installed (`pip install -r requirements.txt`)
and the backend's `.env` to be present (for any that touch the database).

```bash
# from the project root (elite-powerplay-app/)
python backend/scripts/admin/create_admin.py
python backend/scripts/util/check_urls.py
```

## What these scripts are NOT

- They are **not** part of the runtime API — the FastAPI app does not import
  from this directory.
- They are **not** a test suite. Real tests should live in a `tests/` folder
  and be runnable by `pytest`. (See `docs/VERSIONING.md` for the roadmap to
  add proper tests.)
- They are **not** guaranteed to be idempotent. Many write to stdout only,
  but always read the script before running it on production data.

## History

These scripts were originally scattered in the project root with leading
underscore names (`_debug_*.py`, `_probe_*.py`, etc.) as a convention for
"ad-hoc, not part of the build". They polluted the project root and
risked being picked up by linters and formatters. The cleanup pass moved
them here so the root only contains real package files.
