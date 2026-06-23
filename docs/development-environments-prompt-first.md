# Development Environments and Prompt-First Workflow

## Goal
Standardize team development for 2 developers using AI agents, with safe promotion across:
- local (per developer),
- staging (shared),
- production (shared).

This document is the operational source of truth.

## Environment model

| Environment | Owner | Branch source | Database | Purpose |
| --- | --- | --- | --- | --- |
| Local | Each developer | `feature/*` | Local DB per machine | Build and iterate quickly without conflicts |
| Staging | Team shared | `develop` | Shared staging DB | Integrated validation before release |
| Production | Team shared | `main` | Shared production DB | Real usage, controlled changes only |

Critical rule: local never points to staging or production DB.

## New developer onboarding (copy/paste)

Use this exact message with your teammate:

```text
Nuno, here is the repository: <GITHUB_REPO_URL>.

For every task, ask your AI engine to:
1) checkout develop and create feature/<topic> from it,
2) implement only the requested scope,
3) run backend tests and frontend build,
4) if schema changed, validate alembic heads (single head) and run alembic upgrade head,
5) commit and push your feature branch,
6) open PR to develop with test evidence.

Never push directly to main or develop.
```

First local run for a new developer:
1. Clone repository.
2. Run from repo root:
   - `npm install`
   - `npm run dev:all`
3. Login with the default local user created automatically on backend startup:
   - email: `dev@tradingapp.dev`
   - password: `DevPass123!`
4. If needed, change default dev credentials in `backend/.env` using:
   - `DEV_DEFAULT_USER_EMAIL`
   - `DEV_DEFAULT_USER_PASSWORD`
   - `DEV_DEFAULT_USER_DISPLAY_NAME`
   - `DEV_DEFAULT_USER_IS_ADMIN`

## First steps (do this now)

1. Create persistent integration branch:
   - `develop` from current `main`.
2. Configure hosting mappings:
   - Vercel Production from `main`.
   - Vercel Preview from PRs (recommended for `develop` and `feature/*` PRs).
   - Railway staging service/environment tied to `develop`.
   - Railway production service/environment tied to `main`.
3. Configure environment variables per environment (see sections below).
4. Enable CI required checks (workflow in `.github/workflows/ci.yml`).
5. Adopt the task playbooks in this document for all work.

## Branching and merge policy

- `main`: production-ready only.
- `develop`: integration and staging-ready.
- `feature/<topic>`: one task per branch, short-lived.
- `hotfix/<topic>`: urgent production fixes, merged to both `main` and `develop`.

Required flow:
1. Branch from `develop`.
2. Open PR into `develop`.
3. CI must pass.
4. Validate on staging.
5. Promote with PR `develop -> main`.

## Prompt-first team protocol

Use this protocol before every task:
1. "Create a branch from `develop` for `<task>`."
2. "Implement `<task>` with tests and no regressions."
3. "Run backend tests and frontend build."
4. "Show concise diff summary and risks."
5. "Commit and push."
6. "Prepare PR description with test evidence."

Do not let AI skip migration validation or CI checks.

## Step-by-step playbooks by task type

### 1) Backend feature task

1. Branch from `develop`: `feature/backend-<topic>`.
2. Implement API/model/schema changes.
3. If schema changed, create Alembic migration.
4. Run:
   - `cd backend`
   - `.\.venv\Scripts\python.exe -m pytest`
5. Run frontend build if contracts changed:
   - `cd frontend`
   - `npm run build`
6. Commit, push, PR to `develop`.

Prompt template:
```text
On branch feature/backend-<topic>, implement <topic>.
If DB schema changes, create Alembic migration.
Run backend pytest and frontend build.
Summarize changes and commit with a why-focused message.
```

### 2) Frontend feature task

1. Branch from `develop`: `feature/frontend-<topic>`.
2. Implement UI/API integration changes.
3. Run:
   - `cd frontend`
   - `npm run build`
4. If backend contract touched, run backend tests too.
5. Commit, push, PR to `develop`.

Prompt template:
```text
On branch feature/frontend-<topic>, implement <topic> in frontend.
Keep API contracts compatible with backend.
Run npm run build and fix any regressions before commit.
```

### 3) Schema change task (migration-sensitive)

1. Rebase branch on latest `develop`.
2. Create model changes and Alembic migration.
3. Validate migration chain:
   - `cd backend`
   - `alembic heads` (must be one head)
   - `alembic upgrade head`
4. Run `pytest`.
5. Commit migration + model + tests together.

Prompt template:
```text
Implement schema change <topic> with SQLAlchemy model + Alembic migration.
Ensure alembic heads returns exactly one head.
Run alembic upgrade head and pytest before commit.
```

### 4) Hotfix in production

1. Branch from `main`: `hotfix/<topic>`.
2. Implement minimal safe fix.
3. Run backend tests and frontend build locally.
4. PR to `main`, deploy production.
5. Back-merge same fix into `develop`.

Prompt template:
```text
Create hotfix/<topic> from main.
Apply minimal safe fix, run tests/build, and prepare PR to main.
After merge, back-merge the same fix into develop.
```

### 5) Release `develop` to `main`

1. Confirm `develop` CI is green.
2. Execute staging smoke tests.
3. PR `develop -> main`.
4. Execute production smoke tests.
5. Tag release (optional but recommended).

## Migration guardrails (parallel AI development)

Mandatory checks for any DB-related PR:
- `alembic heads` returns one head.
- Migration is present in `backend/alembic/versions`.
- Model and migration are committed together.
- No manual schema edits outside Alembic.
- Test evidence included in PR.

Conflict prevention:
- Always rebase feature branches before generating migration files.
- Avoid two simultaneous schema branches without coordination.

## CI policy

CI must run on push/PR to `develop` and `main`:
- backend: pytest,
- frontend: production build.

Merge is blocked on CI failure.

## Environment variable baselines

### Backend
- Local: `backend/.env` from `backend/.env.example`
- Staging: based on `backend/.env.staging.example`
- Production: based on `backend/.env.production.example`

Required:
- `DATABASE_URL` (environment-specific),
- `JWT_SECRET_KEY` (strong, unique per environment),
- `CORS_ALLOW_ORIGINS` (include matching frontend origin),
- `ENV` (`dev`, `staging`, `production`).

### Frontend
- Local: `frontend/.env` from `frontend/.env.example`
- Staging: `frontend/.env.staging.example`
- Production: set in Vercel project settings.

Required:
- `VITE_API_BASE_URL` must point to the matching backend environment.

## Deploy runbook

### Staging deploy checklist

1. Merge PR into `develop`.
2. Confirm CI green on `develop`.
3. Deploy to staging (automatic or manual according to host config).
4. Run smoke tests:
   - `GET /health`
   - login (`POST /auth/login`)
   - one authenticated endpoint (for example `/signals/strategies`).
5. Validate frontend points to staging backend.

### Production deploy checklist

1. PR `develop -> main` approved and merged.
2. Confirm CI green on `main`.
3. Deploy to production.
4. Run smoke tests:
   - `GET /health`
   - login (`POST /auth/login`)
   - one critical read flow (`/market-data/instruments`).
5. Confirm no emergency rollback needed.

## PR checklist (copy to PR description)

- [ ] Branch is based on latest `develop` (or `main` for hotfix).
- [ ] Backend tests pass.
- [ ] Frontend build passes.
- [ ] Migration included (if schema changed).
- [ ] `alembic heads` single-head validated (if schema changed).
- [ ] Env/docs updated when needed.
- [ ] Smoke-test evidence included for staging/prod-impacting changes.
