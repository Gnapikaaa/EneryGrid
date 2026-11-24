# EnergyGrid Backend (Step 2A: Skeleton & Database Foundation)

FastAPI + PostgreSQL + SQLAlchemy 2.0 + Alembic backend foundation for EnergyGrid.

## Prerequisites

- Python 3.11+
- PostgreSQL 15+ (required for `ON DELETE SET NULL (reading_id)` composite foreign keys and `btree_gist` exclusion constraints)

## Setup

1. Create and activate a virtual environment inside `backend/`:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure environment variables:

Copy the root `.env.example` to `.env` (or export variables directly in your shell) and set valid PostgreSQL connection strings:

- `DATABASE_URL` — primary application database (e.g. `postgresql+psycopg://<user>:<password>@localhost:5432/energygrid`)
- `TEST_DATABASE_URL` — isolated test database used by `pytest` (e.g. `postgresql+psycopg://<user>:<password>@localhost:5432/energygrid_test`)
- `JWT_SECRET_KEY` — 32+ character random secret (mandatory in `staging` and `production`)
- `ALLOW_DEV_AUTH_BYPASS` — must remain `false` in `staging` and `production`

3. Run Alembic migrations:

```bash
cd backend
alembic upgrade head
```

4. Start the FastAPI server (development):

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

5. Verify health & database connectivity:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

Expected response when PostgreSQL is reachable:

```json
{"status":"ok","service":"EnergyGrid API","environment":"development","database":"connected","timestamp":"2026-11-19T00:00:00Z"}
```

## Running Tests

Ensure `TEST_DATABASE_URL` points to a running PostgreSQL 15+ database, then run:

```bash
cd backend
pytest -v
```

## Phase 2B: Authentication & Initial Administrator Bootstrap

Authentication endpoints under `/api/v1`:

- `POST /api/v1/auth/register` — Public viewer-only registration (`role` is always assigned `viewer`; privileged roles or extra fields are rejected).
- `POST /api/v1/auth/login` — Email/password login returning a signed HS256 JWT access token.
- `GET /api/v1/auth/me` — Returns the authenticated user's profile (requires `Authorization: Bearer <token>`).
- `GET /api/v1/users`, `GET /api/v1/users/{user_id}`, `PATCH /api/v1/users/{user_id}` — Admin-only user management endpoints (role/status changes use the database as the authoritative source; admins cannot demote or deactivate themselves).

Bootstrap the first administrator interactively (passwords are prompted securely via `getpass` and never accepted as CLI arguments):

```bash
cd backend
python -m app.cli.create_admin --email admin@energygrid.example --full-name "Grid Administrator"
```

## Phase 2C: Core CRUD APIs (Facilities, Zones, Meters)

Migration `0002_soft_deactivation` adds `is_active`, `deactivated_at`, `consistent_deactivation_state` check constraints, and active-status indexes to `facilities` and `zones` (matching `meters`).

Endpoints under `/api/v1` (all return `401` when unauthenticated; list endpoints return `PaginatedResponse` with `page` >= 1 and `1 <= page_size <= 100`):

- **Facilities**:
  - `GET /api/v1/facilities` (`is_active`, `search`, `page`, `page_size`)
  - `GET /api/v1/facilities/{facility_id}`
  - `POST /api/v1/facilities` (`admin` only)
  - `PATCH /api/v1/facilities/{facility_id}` (`admin` only)
  - `POST /api/v1/facilities/{facility_id}/deactivate` (`admin` only; blocked with `409` while active zones or meters exist)
  - `DELETE /api/v1/facilities/{facility_id}` (`admin` only; blocked with `409` if any zones, meters, telemetry, anomalies, or insights exist)
- **Zones**:
  - `GET /api/v1/zones` (`facility_id`, `status`, `is_active`, `search`, `page`, `page_size`)
  - `GET /api/v1/zones/{zone_id}`
  - `POST /api/v1/zones` (`admin` only; requires active parent facility)
  - `PATCH /api/v1/zones/{zone_id}` (`admin` only)
  - `POST /api/v1/zones/{zone_id}/deactivate` (`admin` only; blocked with `409` while active meters exist)
  - `DELETE /api/v1/zones/{zone_id}` (`admin` only; blocked with `409` if any meters, insights, telemetry, or anomalies exist)
- **Meters**:
  - `GET /api/v1/meters` (`facility_id`, `zone_id`, `status`, `is_active`, `search`, `page`, `page_size`)
  - `GET /api/v1/meters/{meter_id}`
  - `POST /api/v1/meters` (`admin` only; requires active parent facility and matching active zone)
  - `PATCH /api/v1/meters/{meter_id}` (`admin` or `utility_engineer`; zone reassignment blocked with `409` if telemetry or anomaly history exists)
  - `POST /api/v1/meters/{meter_id}/deactivate` (`admin` only; preserves telemetry, anomalies, and calibration audits)
  - `DELETE /api/v1/meters/{meter_id}` (`admin` only; blocked with `409` if any telemetry, anomalies, or calibration audits exist)

### Role Permissions (Phase 2C)

- `admin`: Full CRUD, deactivation, and guarded deletion across facilities, zones, and meters.
- `facility_manager`: Strictly read-only across facilities, zones, and meters until a `user_facility_assignments` migration is introduced.
- `utility_engineer`: Read access to all facilities, zones, and meters; update (`PATCH`) access on meters only.
- `viewer`: Strictly read-only across facilities, zones, and meters.

## Phase 2D: Telemetry Ingestion

Endpoints under `/api/v1/telemetry` (all require authentication; `POST` endpoints require `admin` or `utility_engineer`; `facility_manager` and `viewer` are strictly read-only):

- `POST /api/v1/telemetry/readings` — Single-reading ingestion (`201`). Validates active `Facility`/`Zone`/`Meter` hierarchy (`FOR SHARE` lock on `meters`), UTC-normalized timezone-aware timestamps, configurable overload factor (`TELEMETRY_MAX_OVERLOAD_FACTOR`, default `3.0x rated_kw`), `energy_kwh` derivation (`actual_kw * interval_seconds / 3600`) or tolerance validation (`±(5% + 0.05 kWh)` without overwriting supplied values), duplicate `(meter_id, recorded_at)` (`409`), and GiST interval overlap (`409`).
- `POST /api/v1/telemetry/readings/bulk` — Batch ingestion (`200`). Defaults to `atomic=false` (partial success via per-row `SAVEPOINT`s inside a single outer transaction); supports `atomic=true` for full rollback on any error. Capped by `TELEMETRY_MAX_BULK_ITEMS` (default `1000`).
- `POST /api/v1/telemetry/readings/upload` — Streaming multipart CSV upload (`200`, supports `?atomic=true|false`). Enforces `TELEMETRY_MAX_CSV_UPLOAD_BYTES` (default `10 MiB`) and `TELEMETRY_MAX_CSV_UPLOAD_ROWS` (default `10,000`) while reading without loading the full upload into memory; forces `source='csv_import'` and reports 1-based `row_number` errors.
- `GET /api/v1/telemetry/readings` — Paginated reading retrieval (`page >= 1`, `1 <= page_size <= 100`) filterable by `facility_id`, `zone_id`, `meter_id`, `start_at`, `end_at`, `quality_flag`, and `source`.

## Phase 2E: Rolling Baselines, Anomaly Detection, Energy Insights & Bounded Analytics

Migration `0003_phase2e_analytics` upgrades from `0002_soft_deactivation`, adding bounded baseline retry tracking columns and partial pending index on `telemetry_readings`, nullable `estimated_cost` + `cost_estimate_status` + partial unique `uq_anomalies_reading_id` on `anomalies`, and `meter_id` / `rule_code` / `dedupe_key` / `cost_estimate_status` / `savings_basis` / JSONB `evidence` + partial active unique index `uq_insights_active_dedupe` on `energy_insights` (with safe deterministic legacy row backfill).

### Endpoints under `/api/v1`

- **Bounded Analytics Processing (`admin` or `utility_engineer` only)**:
  - `POST /api/v1/analytics/process` — Synchronously processes bounded batches (`ANALYTICS_CHUNK_SIZE` default `250`, `max_readings` default `2500`, hard cap `20000`) in per-meter chunks ordered by `(meter_id ASC, recorded_at ASC, id ASC)`.
  - Supports strict keyset cursor pagination (`cursor: {last_meter_id, last_recorded_at, last_reading_id}` validated against DB existence, timestamp, and scope -> `422` on mismatch), `reprocess`, `retry_insufficient`, and isolated `retry_exhausted` recovery (mutually exclusive with `reprocess` and `retry_insufficient` -> `422`).
- **Anomalies (`GET` all authenticated roles; mutations `admin` or `utility_engineer` only)**:
  - `GET /api/v1/anomalies` (`facility_id`, `zone_id`, `meter_id`, `status`, `severity`, `min_z_score`, `start_at`, `end_at`, `page`, `page_size`)
  - `GET /api/v1/anomalies/{anomaly_id}` & `GET /api/v1/anomalies/{anomaly_id}/history`
  - `POST /api/v1/anomalies/{anomaly_id}/acknowledge` (`Open -> Acknowledged`)
  - `POST /api/v1/anomalies/{anomaly_id}/investigate` (`Open | Acknowledged -> Assigned`, defaults assignee to actor)
  - `POST /api/v1/anomalies/{anomaly_id}/resolve` (`-> Resolved`, non-blank note required)
  - `POST /api/v1/anomalies/{anomaly_id}/reopen` (`Resolved -> Open`, clears assignee, non-blank note required)
- **Energy Insights (`GET` all authenticated roles; mutations `admin` or `utility_engineer` only)**:
  - `GET /api/v1/insights` (`facility_id`, `zone_id`, `meter_id`, `status`, `priority`, `category`, `page`, `page_size`)
  - `GET /api/v1/insights/{insight_id}` & `GET /api/v1/insights/{insight_id}/history`
  - `PATCH /api/v1/insights/{insight_id}` (`Recommended | In Progress | Implemented` transitions; reactivating an `Implemented` row when another active row owns `dedupe_key` returns `409 Conflict`).

### Rolling Baselines, Financial Rules & Concurrency Guarantees

- **Baselines**: Computed deterministically over strictly earlier `valid`, non-`simulation` readings in the 30-day lookback matching exact `interval_seconds` and facility-local `(hour, weekday/weekend)` buckets (with configurable hour-only fallback), capped at the newest 120 samples. Stores raw Bessel (`n - 1`) `std_dev_kw`; uses `max(sample_std_kw, min_std_dev_kw, min_std_dev_pct * mean_kw)` only as the z-score denominator. Insufficient history leaves `baseline_computed_at = NULL`, increments `baseline_attempt_count` up to `ANALYTICS_INSUFFICIENT_MAX_ATTEMPTS` (`20`), applies exponential cooldown (`baseline_retry_after`), and wakes immediately if earlier historical telemetry (`id > baseline_attempt_max_meter_id`) arrives.
- **Anomalies & Tariff Availability**: Positive-only detection (`actual_kw - raw_mean_kw >= 2.00 kW` and `z_score >= 2.00` Elevated / `2.60` High / `3.40` Critical). Genuine `$0.0000` tariff rates produce `estimated_cost = 0.00` with `cost_estimate_status = 'available'`; unavailable rates yield `estimated_cost = NULL` with `unavailable_tariff`. Reprocessing reconciles metrics idempotently while preserving human workflow states (`Acknowledged`, `Assigned`, `Resolved`).
- **Energy Insights**: Evaluates `PEAK_LOAD_SHIFT` (`tariff_arbitrage_only`), `LOW_POWER_FACTOR` (`not_quantifiable` / `unquantified_telemetry`), `OFF_PEAK_BASELOAD_PATTERN`, and `THERMAL_CORRELATED_LOAD` (Pearson `r` with zero-variance guard and interval-level mixed-tariff summation across positive-excess intervals) once `>= 96` readings and `>= 7` distinct facility-local days exist. `payback_months` remains `NULL`.
- **Advisory Lock DAG**: Meter analytics acquires `pg_advisory_xact_lock(2001, meter)` before reading/updating chunks; insight deduplication and reactivation acquire `pg_advisory_xact_lock(2002, dedupe_key)` **after** `2001` (during analytics runs) and **before** any `energy_insights` `FOR UPDATE` row lock to eliminate deadlocks.
- **RBAC**: `facility_manager` and `viewer` remain strictly read-only (`403` on `/analytics/process`, anomaly actions, and insight status updates).


