# EnergyGrid — Industrial Energy Monitoring Platform

EnergyGrid is a full-stack industrial energy consumption analytics and anomaly detection platform for monitoring energy usage across facilities, zones, and meters. It provides real-time telemetry ingestion, rolling baseline calculation, z-score anomaly detection, incident lifecycle workflows, actionable energy insights, bounded analytics processing, and CSV reporting.

---

## Features

- **Authentication & RBAC**: JWT authentication (`login`, `register`, `me`) and role-based access control (`admin`, `utility_engineer`, `viewer`, `facility_manager`).
- **Facilities, Zones & Meters**: Hierarchical asset registry with soft-deactivation and guarded deletion.
- **Telemetry Ingestion**: Single-reading, bulk batch (`atomic=true|false`), and streaming CSV upload with duplicate and interval-overlap protection.
- **Rolling Baselines**: 30-day lookback over facility-local hour and weekday/weekend buckets with Bessel standard deviation and exponential retry backoff.
- **Z-Score Anomaly Detection & Severity Classification**: Positive-deviation detection classified into `Elevated`, `High`, and `Critical` severities with waste/cost estimation.
- **Incident Lifecycle**: Workflow state transitions (`Open` → `Acknowledged` → `Assigned` → `Resolved` → `Open`) with audit history.
- **Energy Insights**: Automated detection of peak-load shift, low power factor, off-peak baseload, and thermal-correlated load opportunities.
- **Bounded Analytics Processing**: Synchronous chunked processing (`POST /api/v1/analytics/process`) with keyset-cursor pagination and PostgreSQL advisory locks.
- **CSV Reports**: Client-side CSV export for telemetry and anomaly data.

---

## Technology Stack

- **Frontend**: React 19, TypeScript, Vite 6, Tailwind CSS, Vitest
- **Backend**: Python, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, JWT (PyJWT), Argon2id password hashing
- **Database**: PostgreSQL

---

## Project Structure

```
finalOneig/
├── backend/
│   ├── alembic/             # Database migrations
│   ├── app/                 # FastAPI app, API routers, models, schemas, services
│   ├── tests/               # Pytest test suite
│   ├── pyproject.toml
│   └── requirements.txt
├── frontend/
│   ├── public/              # Static assets
│   ├── src/                 # React components, API client, auth context, types, tests
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── .gitignore
├── README.md
└── start-energygrid.bat     # Windows convenience script (frontend)
```

---

## Prerequisites

- **Node.js** 18+
- **Python** 3.11+
- **PostgreSQL** 14+ (15+ recommended for composite `ON DELETE SET NULL` foreign keys and `btree_gist` exclusion constraints)

---

## Setup

### Frontend Setup

```bash
cd frontend && npm install && npm run dev
```

### Backend Setup

```bash
cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
```
*(On macOS/Linux, activate with `source .venv/bin/activate`.)*

---

## Environment Variables

> **Security note**: Never commit `.env` files or secrets. `.gitignore` excludes `.env` and `.env.*` (except `.env.example`).

### Backend (`backend/.env`)

- `DATABASE_URL` (`postgresql+psycopg://...`)
- `TEST_DATABASE_URL`
- `JWT_SECRET_KEY`
- `JWT_ALGORITHM` (default: `HS256`)
- `ACCESS_TOKEN_EXPIRE_MINUTES` (default: `30`)
- `ALLOWED_ORIGINS` (comma-separated, e.g. `http://localhost:5173`)
- `CORS_ALLOW_CREDENTIALS` (default: `true`)

### Frontend (`frontend/.env`, optional)

- `VITE_API_BASE_URL` (default: `http://localhost:8000/api/v1`)

---

## Database Setup

```bash
cd backend && alembic upgrade head
```

---

## Start Commands

- **Backend**:
  ```bash
  cd backend && .venv\Scripts\activate && uvicorn app.main:app --reload
  ```
- **Frontend**:
  ```bash
  cd frontend && npm run dev
  ```
- **Windows convenience script (frontend)**:
  ```bat
  start-energygrid.bat
  ```

---

## API Documentation

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

---

## API Architecture

All backend endpoints are mounted under `/api/v1` across 10 router modules:

| Router Module | Base Path | Purpose |
|---|---|---|
| `health` | `/api/v1/health` | Service and database health check |
| `auth` | `/api/v1/auth` | User registration, login, and current profile (`/me`) |
| `users` | `/api/v1/users` | Admin user listing and role/status management |
| `facilities` | `/api/v1/facilities` | Facility CRUD, deactivation, and deletion |
| `zones` | `/api/v1/zones` | Zone CRUD, deactivation, and deletion |
| `meters` | `/api/v1/meters` | Meter CRUD, deactivation, and deletion |
| `telemetry` | `/api/v1/telemetry/readings` | Single, bulk, and CSV telemetry ingestion & queries |
| `analytics` | `/api/v1/analytics/process` | Bounded batch baseline, anomaly, and insight processing |
| `anomalies` | `/api/v1/anomalies` | Anomaly listing, detail, workflow history, and lifecycle actions |
| `insights` | `/api/v1/insights` | Energy insight listing, detail, history, and status updates |

---

## Testing

- **Backend (`pytest`)**:
  ```bash
  cd backend && .venv\Scripts\python.exe -m pytest tests/ -v
  ```
  *(Note: On Windows environments with AppControl enabled, policy must allow `pydantic_core` native DLLs.)*

- **Frontend (`Vitest`)**:
  ```bash
  cd frontend && node node_modules/vitest/vitest.mjs run
  ```

- **Frontend TypeScript Check**:
  ```bash
  cd frontend && node node_modules/typescript/bin/tsc --noEmit
  ```

---

## Known Limitations

- Charts (`LoadProfileChart`, `ConsumptionHeatmap`) and `ZoneBreakdown` use mock/calculated data; no live telemetry chart endpoint exists in this release.
- Analytics requires `POST /api/v1/analytics/process` — there is no `GET` aggregation endpoint.
- CSV export is generated locally from mock data (no server-side `/reports` endpoint).
- `pytest` requires Windows AppControl policy to allow the `pydantic_core` DLL.

---

## OJT Demo Accounts (by Role)

Do not store or commit account passwords in documentation. Create the initial administrator interactively using `python -m app.cli.create_admin` inside `backend/`.

- **`admin`**: Full CRUD on all resources + analytics processing + user management.
- **`utility_engineer`**: Telemetry ingestion + anomaly lifecycle management + meter updates.
- **`viewer`**: Read-only on all resources.

*(Public registration via `POST /api/v1/auth/register` always creates a `viewer` account; promote users via admin `PATCH /api/v1/users/{id}`.)*
