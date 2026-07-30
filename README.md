# ClassyBattle — Backend (Phase 1 + Phase 2: Foundation, Auth & Tournament Core)

Production-grade FastAPI backend for the ClassyBattle eSports Tournament Platform.

> **Scope note:** Phase 1 (foundation + authentication) and Phase 2 (Tournament Core) are
> implemented. Wallet, Payments, Referral, and Admin Dashboard business logic are
> intentionally **not** implemented yet — the architecture is preserved so these plug in
> cleanly in later phases.

## Phase 2 — Tournament Core

Adds the `tournaments` table and a full REST module under `/api/v1/tournaments`:

- Full CRUD (create, update, get by id/slug, list, soft delete) with pagination, sorting,
  and filtering (by game, status, visibility, featured flag, and text search).
- Automatic, collision-safe slug generation (`app/utils/slug.py`).
- Status machine covering Draft → Published → Registration Open → Registration Closed →
  Live → Completed → Archived, plus Cancelled, with transitions validated centrally in
  `app.models.tournament.TOURNAMENT_STATUS_TRANSITIONS`.
- Banner/cover image upload to Supabase Storage (reuses the Phase 1 `StorageService`), with
  content-type and size (5 MB) validation.
- Authorization: any verified user can create a tournament (becoming its owner); only the
  owner or an admin/super_admin can update, change status, delete, or upload assets.
- Validation: date-window consistency, positive/non-negative numeric fields, max/current
  player bounds, and duplicate-title-per-game checks — enforced in both the service layer
  and as DB `CHECK`/`UNIQUE` constraints (`migrations/versions/0002_tournaments.py`).

---

## 1. Tech Stack

- Python 3.13, FastAPI, Uvicorn
- SQLAlchemy 2.0 (async) + Alembic
- PostgreSQL (Supabase-hosted)
- Supabase Storage (setup only)
- Firebase Cloud Messaging (setup only)
- Brevo transactional email API
- JWT auth (python-jose) + passlib/bcrypt
- Pydantic v2, structlog, slowapi (rate limiting)
- Docker / docker-compose

## 2. Architecture

Clean Architecture, layered:

```
app/
  api/v1/          # Route handlers (thin controllers)
  core/             # security, exceptions, logging, password policy
  config/           # Settings (pydantic-settings)
  database/         # engine/session, declarative base + mixins
  models/           # SQLAlchemy ORM models
  schemas/          # Pydantic request/response models
  repositories/      # Repository Pattern — DB access only
  services/         # Business logic, orchestrates repositories
  dependencies/     # FastAPI DI (current user, role guards)
  middleware/       # logging, rate limiting, exception handlers
  storage/           # Supabase Storage wrapper
  notifications/     # Firebase push + in-app notification infra
  emails/            # Brevo EmailService + HTML templates
  utils/             # OTP generation, avatar catalogue
  main.py            # App factory / entrypoint
migrations/           # Alembic (async-aware)
tests/                 # Pytest suite
scripts/               # seed_games.py
```

Request flow: **Route → Service → Repository → DB**. Routes never touch the DB directly.

## 3. Authentication Flows

**Signup:** `POST /auth/signup` → creates a pending unverified account, sends email OTP (Brevo)
→ `POST /auth/signup/verify-otp` → activates account, returns access + refresh JWTs.

**Login:** `POST /auth/login` → email + password → JWT pair (requires verified email).

**Forgot Password:** `POST /auth/password/forgot` → OTP emailed → `POST /auth/password/verify-otp`
(non-destructive check) → `POST /auth/password/reset` → sets new password, revokes all refresh tokens.

**Tokens:** `POST /auth/token/refresh` to rotate access tokens; `POST /auth/logout` to revoke a refresh token.

OTPs are hashed at rest, rate-limited (resend cooldown + hourly cap), attempt-limited, and single-use.

## 4. Roles

`user`, `admin`, `super_admin` — enforced via the `RequireRole` FastAPI dependency
(`app/dependencies/auth.py`). Admin/Super Admin business endpoints arrive in a later phase;
the middleware is ready now.

## 5. Dynamic Game System

`games` table + `user_game_profiles` table use JSONB columns (`profile_schema` / `data`) so
**new games never require a schema migration**. Each `Game.profile_schema` defines the fields
required for that game's player profile (e.g. Free Fire → nickname + UID, Valorant → Riot ID);
`GameService` validates submitted profiles against it dynamically.

## 6. Getting Started

### Local (Docker — recommended)

```bash
cp .env.example .env   # fill in Supabase / Brevo / Firebase credentials
docker compose up --build
```

API available at `http://localhost:8000`, Swagger docs at `http://localhost:8000/docs`.

### Local (without Docker)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit values
alembic upgrade head
python -m scripts.seed_games   # optional: seed Free Fire / BGMI / COD Mobile / Valorant
uvicorn app.main:app --reload
```

### Running Migrations

```bash
alembic upgrade head              # apply
alembic revision --autogenerate -m "message"   # generate new migration
```

### Running Tests

```bash
pytest
```
> Models use PostgreSQL-specific types (UUID, JSONB); point `DATABASE_URL` at a disposable
> Postgres instance (e.g. `docker compose up db`) to run the full suite end-to-end.

## 7. Environment Variables

See `.env.example` for the full list (app, database, JWT, OTP, Supabase, Brevo, Firebase, CORS,
rate limiting, logging).

## 8. Explicitly Out of Scope (Phase 1 + 2)

Wallet, Add/Withdraw Money, Referral, Admin Dashboard business features, Payment Gateway
integration, and tournament registration/bracket/match logic — architecture is preserved so
these plug in cleanly later.
