# Versioning policy — N-1 pinning

## TL;DR

Every runtime dependency in this project is pinned to the **N-1** version —
the previous stable major/minor. We don't track the bleeding edge.

## Why N-1?

Three reasons, in order of importance:

1. **Stability over novelty.** The app runs the Power-Play recommendations
   and Spansh enrichment pipeline. A regression in a "new" major version
   of FastAPI, Pydantic, or React is a real outage for users. Sitting one
   step behind means we get the bug fixes from the latest version without
   absorbing its breaking-change risk.

2. **Time-to-fix compatibility.** When a library ships a breaking change
   (e.g. Pydantic 2.11 → 3.x), the ecosystem takes 2-4 months to catch up
   (type stubs, plugin compatibility, etc.). N-1 means we have time to
   plan the migration rather than be the canary.

3. **Reproducible builds.** Exact pins (`==` for Python, no `^` for npm)
   mean a `pip install` or `npm ci` in six months will produce byte-for-byte
   the same dependency tree. Combined with `requirements.lock.txt` and
   `package-lock.json` (both tracked in git), CI is deterministic.

## Current N-1 pins (as of this commit)

### Frontend (`frontend/package.json`)

| Package | Our pin | Latest (N) | N-1 rationale |
|---|---|---|---|
| react | 18.3.1 | 19.x | 19 changed default rendering semantics; ecosystem still catching up |
| react-dom | 18.3.1 | 19.x | matches react |
| react-router-dom | 6.28.0 | 7.x | 7 has data-router API rewrite; 6 is the last stable v6 |
| d3 | 7.8.5 | 7.9.x | d3 ships minor bumps often; we skip those |
| @react-three/fiber | 8.17.10 | 9.x | 9 has React 19-only changes |
| @react-three/drei | 9.122.0 | 10.x | matches @react-three/fiber 8.x peer |
| three | 0.166.1 | 0.17x | 0.17x is the v8-line bridge; safer one back |
| typescript | 5.6.3 | 5.7.x | 5.7 added strict builtin iterator types — not needed |
| vite | 6.3.5 | 7.x | 7 changed CSS HMR defaults |
| @vitejs/plugin-react | 4.3.4 | 4.3.x | stays on 4.3 line for vite 6 compat |

### Backend (`backend/requirements.txt`)

| Package | Our pin | Latest (N) | N-1 rationale |
|---|---|---|---|
| fastapi | 0.114.6 | 0.115.x | 0.115 changed lifespan event semantics |
| uvicorn | 0.30.6 | 0.31+ | stays on 0.30 line for fastapi 0.114 |
| sqlalchemy | 2.0.36 | 2.0.x | stays on 2.0.36 for psycopg 3.2 compat |
| psycopg | 3.2.3 | 3.2.x | matches sqlalchemy 2.0.36 |
| pydantic | 2.10.6 | 2.11+ | 2.11 requires pydantic-core 2.33+; the 2.10 branch has wider plugin support |
| pydantic-core | 2.27.2 | 2.33+ | matches pydantic 2.10 |
| python-jose | 3.3.0 | 3.3.x | stable; no major in years |
| bcrypt | 4.2.1 | 4.2.x | stable |
| httpx | 0.27.2 | 0.28+ | 0.28 changed multipart handling; 0.27 is the safe pick |
| requests | 2.32.3 | 2.32.x | stable |
| apscheduler | 3.10.4 | 3.11+ | 3.11 dropped Python 3.9; we pin 3.10 |
| openai | 1.82.0 | 1.x | openai 2.x has breaking changes; we stay on 1.x |

## Bump cadence

- **Quarterly** (every 3 months): review `npm outdated` and `pip list --outdated`,
  pick the next N-1 candidate for any package that has a stable newer
  release, and open a PR titled `[deps] bump to <package> <new-N-1>`.
- **Ad-hoc** (as needed): bump immediately for any security CVE in a current
  N-1 version, or if a critical bug fix only ships in the new N.
- **Never**: bump multiple unrelated packages in a single commit. One
  package per PR keeps the diff small and the regression search easy.

## Bump procedure

1. Open a PR that changes only the pin line(s).
2. Update `requirements.lock.txt` (`pip install -r requirements.txt && pip freeze > requirements.lock.txt`) or regenerate `package-lock.json` (`rm -rf node_modules && npm install`).
3. Run the full test suite + `npm run build` + `python -c "import main"`.
4. Boot the dev stack end-to-end (ingest → analyze → enrich).
5. Reviewer checks for any deprecation warnings in the runtime logs.
6. Merge only if all of the above pass.

## N vs N-1 vs N+1 cheat sheet

| Strategy | When to use |
|---|---|
| **N+1** (latest + 1, i.e. RC / beta) | Never in this project. That's how outages happen. |
| **N**   (latest stable) | Only for libraries where we're confident the maintainer is responsive and we have time to roll back. Not the default. |
| **N-1** (default) | The default. One step behind latest stable. |
| **N-2** | Reserved for libraries with a history of breaking changes (e.g. Pydantic 1→2→3). Use only when N-1 itself is risky. |

## How to check what we're using

```bash
# Outdated deps (N-1 candidates)
cd frontend && npm outdated
cd backend  && pip list --outdated

# Or use the convenience script
cd frontend && npm run audit-deps
```

A row in the output means N is newer than our pin. The decision to bump
follows the procedure above.
