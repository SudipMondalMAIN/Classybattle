# ClassyBattle API

Production backend for **ClassyBattle**, an eSports tournament platform — tournament creation and management, team/participant registration, room & match lifecycle, live match scoring, prizes & wallet payouts, leaderboards, notifications, moderation/anti-cheat, and social features.

Built with **FastAPI + SQLAlchemy (async) + PostgreSQL + Alembic**, containerized with **Docker**.

---

## 1. Project Overview

ClassyBattle exposes a versioned REST API (`/api/v1`) consumed by web/mobile clients. The backend handles:

- Account creation, OTP-based email verification, JWT auth (access + refresh tokens)
- Tournament, game, game mode, and map management
- Team formation and participant registration (with entry fees)
- Room assignment and match lifecycle management
- Live match scoring and result/winner recording
- Wallet, payments, and prize/commission settlement (with idempotency guards and row-level locking)
- Leaderboards and player/team statistics
- Notifications (in-app + push via Firebase) and email (via Brevo)
- Social features (follows, community posts) and moderation/anti-cheat tooling
- Admin dashboards, audit logging, and security/fraud tracking

## 2. Features

- **Auth**: JWT access/refresh tokens, OTP email verification, password hashing via `passlib`/`bcrypt`, password policy enforcement
- **Rate limiting**: per-route limits via `slowapi`, with a consistent `429` error envelope
- **Idempotency**: idempotency-key support on sensitive write endpoints (e.g. payments/withdrawals) to prevent duplicate processing
- **Transaction safety**: row locking on wallet/prize settlement paths to avoid race conditions on concurrent requests
- **Structured logging**: request-scoped structured logs (`structlog`) with consistent event naming
- **Consistent API envelope**: uniform success/error response shapes and centralized exception handlers
- **Admin-gated workflows**: withdrawal approval/rejection, moderation actions, and broadcast notifications restricted to admin roles
- **Audit logging**: sensitive admin/financial actions are recorded for traceability
- **Environment-aware docs**: Swagger/Redoc/OpenAPI JSON auto-disabled in production unless explicitly re-enabled

## 3. Architecture

Layered architecture, request flow:

```
Client -> FastAPI Router (app/api/v1) -> Service (app/services) -> Repository (app/repositories) -> SQLAlchemy Model (app/models) -> PostgreSQL
                                              ^
                                       Schemas (app/schemas) validate I/O at the boundary
```

- **Routers** (`app/api/v1`): HTTP concerns only — auth dependency, request/response schema, delegating to a service.
- **Services** (`app/services`): business logic, transaction boundaries (`commit`/`rollback`), orchestration across repositories.
- **Repositories** (`app/repositories`): data access only — queries, inserts/updates, no business rules.
- **Models** (`app/models`): SQLAlchemy ORM models, one module per domain entity, relationships use `lazy="selectin"` to avoid N+1 lookups on hot paths.
- **Schemas** (`app/schemas`): Pydantic request/response contracts, kept separate from ORM models.
- **Core** (`app/core`): cross-cutting concerns — security (JWT/hashing), password policy, structured logging, request context, exception types.
- **Middleware** (`app/middleware`): request logging, rate limiting, centralized exception → HTTP response mapping.
- **Dependencies** (`app/dependencies`): shared FastAPI dependencies (current user, DB session, role checks).
- **Notifications / Emails** (`app/notifications`, `app/emails`): push (Firebase) and email (Brevo) delivery, decoupled from business services via a dispatch service.
- **Storage** (`app/storage`): Supabase-backed file storage helpers.

## 4. Folder Structure

```
Classybattle/
├── app/
│   ├── api/v1/          # Route modules + router aggregation
│   ├── config/          # Settings (pydantic-settings)
│   ├── core/             # security, logging, exceptions, password policy, request context
│   ├── database/        # engine/session setup, custom types
│   ├── dependencies/    # shared FastAPI dependencies
│   ├── emails/           # Brevo email templates/service
│   ├── middleware/      # logging, rate limiting, exception handlers
│   ├── models/           # SQLAlchemy ORM models
│   ├── notifications/   # push notifications + dispatch service
│   ├── repositories/    # data-access layer
│   ├── schemas/          # Pydantic request/response models
│   ├── services/         # business logic layer
│   ├── storage/          # Supabase storage helpers
│   ├── utils/            # generic helpers
│   └── main.py           # app factory / entrypoint
├── migrations/           # Alembic migration environment + versions
├── scripts/               # one-off/maintenance scripts (e.g. seed_games.py)
├── tests/                 # pytest suite
├── Dockerfile
├── docker-compose.yml        # local development
├── docker-compose.prod.yml   # production overlay
├── requirements.txt          # production dependencies
├── requirements-dev.txt      # + test dependencies
├── alembic.ini
└── .env.example
```

## 5. Installation

### Prerequisites
- Python 3.13+
- PostgreSQL 16+ (or use the bundled Docker Compose Postgres)
- Docker + Docker Compose (recommended)

### Local (without Docker)

```bash
git clone https://github.com/SudipMondalMAIN/Classybattle.git
cd Classybattle
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # includes test dependencies
cp .env.example .env                  # then edit .env
alembic upgrade head
uvicorn app.main:app --reload
```

API available at `http://localhost:8000`, docs at `http://localhost:8000/docs` (non-production only).

## 6. Configuration

All configuration is loaded from environment variables via `app/config/settings.py` (`pydantic-settings`), backed by a `.env` file locally. See `.env.example` for the full template.

## 7. Environment Variables

| Variable | Description | Default |
|---|---|---|
| `APP_NAME` | Application name shown in OpenAPI | `ClassyBattle` |
| `APP_ENV` | `development` \| `staging` \| `production` | `development` |
| `APP_DEBUG` | Debug flag (keep `false` in production) | `false` |
| `API_V1_PREFIX` | API route prefix | `/api/v1` |
| `SECRET_KEY` | App-level secret | **required** |
| `DATABASE_URL` | Async SQLAlchemy DB URL (asyncpg) | **required** |
| `DATABASE_URL_SYNC` | Sync DB URL (used by Alembic) | **required** |
| `DB_POOL_SIZE` | SQLAlchemy connection pool size | `10` |
| `DB_MAX_OVERFLOW` | Extra connections beyond pool size | `20` |
| `DB_ECHO` | Log all SQL statements | `false` |
| `JWT_SECRET_KEY` | JWT signing secret | **required** |
| `JWT_ALGORITHM` | JWT signing algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime | `30` |
| `OTP_LENGTH` | OTP digit length | `6` |
| `OTP_EXPIRY_MINUTES` | OTP validity window | `10` |
| `OTP_MAX_ATTEMPTS` | Max verification attempts | `5` |
| `OTP_RESEND_COOLDOWN_SECONDS` | Cooldown between resend requests | `60` |
| `OTP_MAX_PER_HOUR` | Max OTPs issued per hour | `5` |
| `SUPABASE_URL` / `SUPABASE_KEY` | Supabase project + service key (storage) | `""` |
| `SUPABASE_STORAGE_BUCKET` | Storage bucket name | `classybattle-assets` |
| `BREVO_API_KEY` / `BREVO_SENDER_EMAIL` / `BREVO_SENDER_NAME` | Transactional email (Brevo) | — |
| `FIREBASE_CREDENTIALS_PATH` / `FIREBASE_PROJECT_ID` | Push notifications | — |
| `CORS_ORIGINS` | JSON list or comma-separated origins | `["http://localhost:3000"]` |
| `RATE_LIMIT_PER_MINUTE` | Default per-route rate limit | `60` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `ENABLE_API_DOCS` | Force docs on/off regardless of `APP_ENV` | unset (auto: off in production) |

**Never commit a real `.env`.** Rotate `SECRET_KEY` / `JWT_SECRET_KEY` per environment and store them in your platform's secret manager in production.

## 8. Database Setup

Postgres is required. With Docker Compose, the `db` service provisions it automatically. Standalone:

```bash
createdb classybattle
```

Set `DATABASE_URL` (async, `asyncpg`) and `DATABASE_URL_SYNC` (sync, `psycopg2`) to point at it, then run migrations (see below).

## 9. Alembic Usage

```bash
# Apply all migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "describe change"

# Roll back one revision
alembic downgrade -1

# Inspect current DB revision
alembic current
```

Migration environment lives in `migrations/env.py`; individual revisions are in `migrations/versions/`. Always review autogenerated migrations before applying — autogenerate can miss constraint/index renames.

## 10. Docker Usage

**Development** (hot reload, source bind-mounted):

```bash
docker compose up --build
```

**Production** (immutable image, multi-worker, no bind mount, no host-exposed DB port):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Run migrations inside the running container:

```bash
docker compose exec api alembic upgrade head
```

The image runs as a non-root user (`appuser`) and exposes a container `HEALTHCHECK` against `/api/v1/health`.

## 11. API Overview

Base path: `/api/v1`. All routers are aggregated in `app/api/v1/router.py`. Key route groups:

| Group | Prefix area | Purpose |
|---|---|---|
| Auth | `auth` | Signup, login, OTP verification, token refresh |
| Users | `users` | Profile management |
| Wallet / Payments | `wallet`, `payments` | Balance, deposits, withdrawals, settlement |
| Games / Modes / Maps | `games`, `game-modes`, `maps` | Catalog management |
| Tournaments | `tournaments` | Tournament CRUD and lifecycle |
| Teams / Participants | `teams`, `participants` | Registration, team formation |
| Matches / Live Matches | `matches`, `live-matches` | Room assignment, match lifecycle, live scoring |
| Match Results | `match-results` | Winners, result recording |
| Prizes | `prizes` | Prize distribution |
| Leaderboard | `leaderboard` | Player/team rankings |
| Notifications | `notifications` | In-app + push notification preferences and delivery |
| Social / Team Community | `social`, `team-community` | Follows, posts |
| Moderation / Anti-cheat / Security | `moderation`, `anti-cheat`, `security` | Admin enforcement + fraud signals |
| Admin Dashboard | `admin-dashboard` | Aggregate admin views |
| Health | `health` | Liveness/readiness probe |

Full interactive documentation (Swagger UI) is served at `/docs` and the OpenAPI schema at `/openapi.json` in any non-production environment, or when `ENABLE_API_DOCS=true` is explicitly set.

## 12. Deployment Guide

1. Provision PostgreSQL and set `DATABASE_URL` / `DATABASE_URL_SYNC`.
2. Set all **required** env vars (`SECRET_KEY`, `JWT_SECRET_KEY`, DB URLs) via your platform's secret store — never bake secrets into the image.
3. Set `APP_ENV=production` and leave `APP_DEBUG=false`.
4. Build and push the image: `docker build -t classybattle-api:<tag> .`
5. Run migrations against the target database: `alembic upgrade head` (run once, before or during rollout, not per-replica).
6. Deploy the container (or `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`), fronted by a reverse proxy/load balancer that terminates TLS.
7. Point health checks at `GET /api/v1/health`.
8. Configure `CORS_ORIGINS` to your real frontend origin(s) only.

## 13. Production Guide

- **Docs**: leave `ENABLE_API_DOCS` unset in production so Swagger/Redoc/OpenAPI JSON stay disabled automatically; only enable temporarily and intentionally for internal review.
- **Secrets**: rotate `SECRET_KEY`/`JWT_SECRET_KEY` per environment; never reuse dev secrets.
- **Database**: connection pool sized via `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` — tune to your DB's `max_connections` and expected replica count. Keep `DB_ECHO=false`.
- **Rate limiting**: `RATE_LIMIT_PER_MINUTE` and per-route limits (via `slowapi`) protect auth/payment endpoints from abuse; review before raising defaults.
- **Idempotency**: payment/withdrawal endpoints expect an idempotency key — clients must supply one to safely retry.
- **Concurrency safety**: wallet/prize settlement paths use row-level locking; avoid bypassing the service layer for these tables.
- **Logging**: structured JSON logs (`structlog`) are suitable for ingestion by any log aggregator; `LOG_LEVEL` controls verbosity.
- **Process model**: run multiple `uvicorn` workers (see `docker-compose.prod.yml`) or place behind a process manager appropriate to your host (systemd, ECS, k8s, etc.).
- **Migrations**: run `alembic upgrade head` as a separate release step, not automatically on every container boot, to avoid concurrent-migration races across replicas.

## 14. Testing

```bash
pip install -r requirements-dev.txt
pytest
```

Tests use `aiosqlite` for an isolated in-memory async test database (see `tests/conftest.py`).

---

**Note:** This README reflects the current state of the codebase as of Phase 18 (production hardening). Business logic, endpoints, and schemas were not modified beyond hardening/cleanup described above.
