# ClassyBattle — Backend (Phases 1–6: Foundation, Auth, Tournament Core, Game Modes, Registration & Team System)

Production-grade FastAPI backend for the ClassyBattle eSports Tournament Platform.

> **Scope note:** Phase 1 (foundation + authentication), Phase 2 (Tournament Core),
> Phase 3 (Game Modes), Phase 4 (Maps), Phase 5 (Tournament Registration &
> Participants), and Phase 6 (Team System & Invite Management) are implemented.
> Wallet, Payments, Referral, and Admin Dashboard business logic are
> intentionally **not** implemented yet — the architecture is preserved so
> these plug in cleanly in later phases.

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

## Phase 3 — Game Modes

Adds the `game_modes` table and a full REST module under `/api/v1/game-modes`, scoped
per-`Game` (e.g. "Battle Royale" / "Clash Squad" for Free Fire, "Solo" / "Duo" / "Squad"
for BGMI):

- Full CRUD (create, update, get by id, get by slug, list, soft delete) with pagination,
  sorting (`name`, `created_at`, `sort_order`), and filtering (by game, active, featured,
  and text search across name/slug).
- Automatic, collision-safe slug generation, unique per game (`app/utils/slug.py`, reused
  from Phase 2).
- Validation: game must exist and be active, duplicate name/slug within the same game is
  rejected, `min_players`/`max_players`/`max_team_size` are cross-checked for consistency —
  enforced in both the service layer and DB `CHECK`/`UNIQUE` constraints
  (`migrations/versions/0003_game_modes.py`).
- Authorization: read APIs (`list`, `get`, `get by slug`) are public; create, update, and
  soft-delete are restricted to `admin` / `super_admin` via the existing `require_admin`
  dependency (`app/dependencies/auth.py`).
- Tracks `created_by` / `updated_by` for audit purposes, plus `icon_url` / `image_url`,
  `short_name`, `description`, and `sort_order` for client-side display.

## Phase 6 — Team System & Invite Management

Adds `teams` and `team_members` tables plus new `Tournament.registration_mode` /
`team_size` / `max_teams` settings, wired into a full REST module under
`/api/v1/teams` and `/api/v1/tournaments/{id}/teams/*`. Generic by design — works
for Solo (1), Duo (2), Trio (3), Squad (4), 5v5, 6v6, and any future size.

- **Registration modes** on `Tournament`: `solo` (unchanged Phase 5 behaviour),
  `team_invite` (captains create a team and share an invite code), and
  `auto_random` (players register solo, then get shuffled into balanced teams
  after registration closes).
- **Team model**: `team_uid`, `invite_code` (secure, unambiguous 8-char code),
  `team_size`, `current_members`, `status` (`forming` → `locked` → `disbanded`),
  `is_locked`, captain reference, soft delete — all backed by DB `CHECK`/`UNIQUE`
  constraints (`migrations/versions/0006_teams.py`).
- **TeamMember model**: links a user (and, once one exists, their `Participant`
  row) to a team with a `captain`/`member` role.
- **Invite codes**: cryptographically random, unique per team, tournament-scoped
  (joining team A's code always resolves within team A's own tournament), and
  rejected once a team is locked or full.
- **APIs**: create/update/soft-delete team, join via invite code, leave, remove
  member, transfer captain, manual lock/unlock, team details/members/list
  (public + organizer "manage" view with soft-deleted teams visible).
- **Validation**: duplicate joins, team capacity, tournament registration
  window/status, invalid/foreign invite codes, locked teams, "captain must
  transfer before leaving", and `max_teams` enforcement — all in the service
  layer (`app/services/team_service.py`).
- **Auto lock**: a team is automatically locked the moment `current_members`
  reaches `team_size`; captains/organizers/admins may also lock or unlock
  manually before registration closes.
- **Automatic Random Team Assignment**: `AutoTeamAssignmentService`
  (`app/services/auto_team_assignment_service.py`) shuffles all unassigned
  active participants into balanced teams of the configured size once
  registration has closed, reporting any remainder that couldn't fill a full
  team; a `manual_assign` escape hatch lets organizers hand-place the
  remainder or override the shuffle.
- **Organizer APIs**: view all teams (including disbanded), remove any team,
  remove any player from their team, run auto-assignment.
- **Security**: only authenticated + verified users can create/join teams;
  only the team captain (or organizer/admin) can manage a specific team;
  only the tournament's organizer or an admin/super_admin can manage all
  teams for that tournament — enforced via the existing `RequireRole` /
  organizer-ownership pattern from Phases 2 and 5.
- **Participant sync**: joining/leaving a team creates/cancels the underlying
  Phase 5 `Participant` row for the same tournament, so existing capacity
  tracking, payment status, and check-in flows keep working unmodified.

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

## 8. Explicitly Out of Scope (Phases 1–6)

Wallet, Add/Withdraw Money, Referral, Admin Dashboard business features, Payment Gateway
integration, bracket/match logic, and map/lookup modules beyond Game Modes — architecture
is preserved so these plug in cleanly later.
