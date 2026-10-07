# Elite Dangerous Power Play Analyzer

A web application that ingests Elite Dangerous faction and Power Play data,
visualises a faction's territory in three views (table, 2D map, 3D map), and
produces AI-assisted fortify/expand recommendations backed by rule-based scoring.

## Stack

- **Backend** — Python **3.13**, FastAPI, SQLAlchemy, PostgreSQL
- **Frontend** — React 18, TypeScript, Vite 6, D3.js, react-three-fiber (Three.js)
- **Ingestion** — Spansh `factions.json.gz` (streaming via `ijson`) + EDSM API
- **Auth** — Admin-only JWT (HS256, 8-hour expiry); read views are public

---

## Quick Start (Docker Compose)

```bash
# 1. Clone and enter the project directory
cd elite-powerplay-app

# 2. Copy the example env file and fill in your values
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, SECRET_KEY, and optionally AI_API_KEY

# 3. Start all services
docker compose up --build

# 4. Open the app
open http://localhost:3000
```

The backend creates all database tables automatically on first startup.

---

## Local Development (without Docker)

### Backend

> **Python 3.13 is required.** Python 3.14 has no pre-built binary wheels for
> `pydantic-core` or `psycopg` yet, so the build will fail on 3.14.
> Install Python 3.13 first: `sudo apt install python3.13 python3.13-venv`

```bash
cd backend
python3.13 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env               # edit DATABASE_URL and SECRET_KEY
uvicorn main:app --reload
```

API available at <http://localhost:8000>  
Interactive docs at <http://localhost:8000/docs>

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App available at <http://localhost:5173> (proxies `/api` → `http://localhost:8000`)

---

## Running Tests

### Frontend (Vitest)

```bash
cd frontend
npm install
npm test
# or with the interactive UI:
npx vitest --ui
```

### Backend (pytest)

```bash
cd backend
python3.13 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest tests/
# with coverage:
pytest tests/ --cov=services --cov-report=term-missing
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | PostgreSQL connection URL |
| `POSTGRES_PASSWORD` | Yes | `pp_password` | PG password (used by docker-compose) |
| `SECRET_KEY` | Yes | dev key | JWT signing secret |
| `LLM_ENABLED` | No | `false` | Enable LLM recommendation summaries |
| `AI_PROVIDER` | No | `openai` | `openai` or `custom` |
| `AI_API_KEY` | If LLM enabled | — | Provider API key |
| `SPANSH_INGEST_INTERVAL_HOURS` | No | `24` | Spansh ingest schedule |
| `EDSM_SYNC_INTERVAL_HOURS` | No | `6` | EDSM sync schedule |

---

## Sub-Task Status

| # | Description | Status |
|---|---|---|
| 1 | Project Scaffold & Database Schema | ✅ Done |
| 2 | Spansh Data Ingestion Service | ✅ Done |
| 3 | EDSM Power Play Sync Service | ✅ Done |
| 4 | Factions & Systems API Endpoints | ✅ Done |
| 5 | Recommendation Engine (Rule-Based) | ✅ Done |
| 6 | LLM Summary Integration | ✅ Done |
| 7 | Frontend: Selectors & Table View | ✅ Done |
| 8 | Frontend: 2D Map View | ✅ Done |
| 9 | Frontend: 3D Map View | ✅ Done |
| 10 | Admin Panel & Ingestion Status UI | ✅ Done |

---

## Creating the first admin user

Use the included utility script (run from the `backend/` directory):

```bash
python3 create_admin.py
# or with custom credentials:
ADMIN_EMAIL=you@example.com ADMIN_PASSWORD=s3cr3t python3 create_admin.py
```

The script is idempotent — running it twice will not create duplicate users.
