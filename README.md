# App Trading

Plataforma de anÃ¡lise e decisÃ£o de trading em modo **PAPER** (sem execuÃ§Ã£o de ordens reais): mercado, sinais, simulaÃ§Ã£o histÃ³rica e memÃ³ria institucional entre runs.

## Estado actual (Jun 2026)

| Ãrea | DisponÃ­vel |
|------|------------|
| Mercado | HistÃ³rico + tempo real (grÃ¡fico, indicadores, IBKR stream) |
| Sinais | HistÃ³rico + live (`POST /signals/evaluate-live`), overlay no grÃ¡fico |
| SimulaÃ§Ã£o | Backtest realista, walk-forward, export CSV, anÃ¡lise crÃ­tica por run |
| MemÃ³ria | LiÃ§Ãµes e recomendaÃ§Ãµes entre simulaÃ§Ãµes, botÃ£o **Aplicar sugestÃ£o** |
| Auth | JWT multi-utilizador, combinaÃ§Ãµes de estratÃ©gias partilhadas |

DocumentaÃ§Ã£o de estado: `docs/status-2026-06-30.md`

## Desenvolvimento em paralelo (prompt-first)

Guia operacional completo:
- `docs/development-environments-prompt-first.md`

Specs de frentes paralelas (AI agents):
- Real-time data feed: `docs/realtime-data-feed-spec.md`
- Plano Backtesting/SimulaÃ§Ã£o: `docs/backtesting-phase-plan.md`

ConvenÃ§Ã£o de branches:
- `main`: produÃ§Ã£o
- `develop`: integraÃ§Ã£o/staging
- `feature/<tema>`: trabalho por tarefa
- `hotfix/<tema>`: correÃ§Ãµes urgentes de produÃ§Ã£o

Ambientes e templates:
- Backend local: `backend/.env.example`
- Backend staging: `backend/.env.staging.example`
- Backend production: `backend/.env.production.example`
- Frontend local: `frontend/.env.example`
- Frontend staging: `frontend/.env.staging.example`
- Frontend production: `frontend/.env.production.example`

CI:
- Workflow em `.github/workflows/ci.yml` (backend pytest + frontend build em `develop` e `main`).

## Stack usada nesta fase

- Backend: FastAPI, Uvicorn, Pydantic, SQLAlchemy, Alembic, structlog
- Frontend: React + TypeScript + Vite
- Base de dados: PostgreSQL (Docker Compose)

## Estrutura

- `backend/` API e infraestrutura Python
- `frontend/` dashboard inicial React
- `docker-compose.yml` PostgreSQL local

## Funcionalidades da fase

- `GET /health` devolve estado da API
- `GET /mode` devolve modo atual (`PAPER`)
- `GET /version` devolve a versÃ£o da API
- `GET /market-data/instruments` lista instrumentos
- `GET /market-data/bars` consulta candles por sÃ­mbolo/timeframe
- `POST /market-data/import-csv` importa CSV OHLCV para PostgreSQL
- `GET /market-data/indicators` calcula indicadores tÃ©cnicos
- `GET /signals/strategies` lista estratÃ©gias disponÃ­veis
- `POST /signals/generate` gera e persiste sinais por estratÃ©gia
- `GET /signals` lista sinais persistidos
- `POST /backtests/run` corre simulaÃ§Ã£o histÃ³rica e persiste resultado
- `GET /backtests` lista backtests do utilizador autenticado (com resumo de insight)
- `GET /backtests/lessons` e `GET /backtests/recommendations` â€” memÃ³ria institucional
- `POST /signals/evaluate-live` â€” sinais na vela em formaÃ§Ã£o
- Dashboard com grÃ¡fico, overlays, simulaÃ§Ã£o e sinais explicados

## PrÃ³xima fase prioritÃ¡ria

**Paper trading em tempo real** â€” ordens simuladas com base em sinais/consenso, portfolio virtual e PnL intraday. O modo `PAPER` e o motor de backtest jÃ¡ existem; falta a camada de execuÃ§Ã£o simulada live.

Melhorias em curso (memÃ³ria v2 + UX):
- valores sugeridos exactos nas recomendaÃ§Ãµes (em vez de deltas heurÃ­sticos),
- resumo de insight na lista de runs,
- aviso quando dados de mercado estÃ£o obsoletos nos sinais live.

HistÃ³rico do plano de backtesting (jÃ¡ entregue): `docs/backtesting-phase-plan.md`

## Como arrancar

### OpÃ§Ã£o rÃ¡pida (recomendado)

Na raiz do projeto, arranca DB + backend + frontend com um Ãºnico comando:

```powershell
npm install
npm run dev:all
```

O arranque local automÃ¡tico tambÃ©m cria (se nÃ£o existir) um utilizador dev no backend:
- email: `dev@tradingapp.dev`
- password: `DevPass123!`

Estas credenciais sÃ£o apenas para `ENV=dev` e podem ser alteradas em `backend/.env` via:
- `DEV_DEFAULT_USER_EMAIL`
- `DEV_DEFAULT_USER_PASSWORD`
- `DEV_DEFAULT_USER_DISPLAY_NAME`
- `DEV_DEFAULT_USER_IS_ADMIN`

### 1) PostgreSQL

```powershell
docker compose up -d postgres
```

### 2) Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8100
```

VariÃ¡veis relevantes no `backend/.env`:

- `CORS_ALLOW_ORIGINS` (ex: `http://localhost:5173,https://trading-kappa-dusky.vercel.app`)
- `JWT_SECRET_KEY` (obrigatÃ³rio para assinatura dos tokens)

CriaÃ§Ã£o de utilizador interno (registo pÃºblico desativado):

```powershell
cd backend
.\.venv\Scripts\python -m app.scripts.create_user --email admin@empresa.com --password "StrongPass123" --display-name "Admin"
```

Nota: em desenvolvimento local via `npm run dev:all`, o bootstrap automÃ¡tico jÃ¡ cria o user dev default.

### 2.1) Importar CSV OHLCV

CSV esperado com colunas: `timestamp,open,high,low,close,volume`.

```powershell
cd backend
.\.venv\Scripts\python -m app.scripts.import_ohlcv --symbol AAPL --timeframe 1d --csv-path .\data\aapl.csv
```

### 3) Frontend

```powershell
cd frontend
npm install
copy .env.example .env
npm run dev -- --host 0.0.0.0 --port 5173
```

VariÃ¡veis relevantes no `frontend/.env`:

- `VITE_API_BASE_URL` (URL pÃºblica do backend)

## ValidaÃ§Ã£o manual rÃ¡pida

1. API em `http://127.0.0.1:8100/health` deve devolver `{"status":"ok"}`
2. API em `http://127.0.0.1:8100/mode` deve devolver `{"mode":"PAPER"}`
3. API em `http://127.0.0.1:8100/version` deve devolver `{"version":"0.1.0"}`
4. Importar um CSV e validar resposta com linhas importadas
5. API em `http://127.0.0.1:8100/market-data/instruments` deve listar o sÃ­mbolo importado
6. API em `http://127.0.0.1:8100/market-data/bars?symbol=AAPL&timeframe=1d` deve devolver candles
7. API em `http://127.0.0.1:8100/market-data/indicators?symbol=AAPL&timeframe=1d` deve devolver indicadores
8. API em `http://127.0.0.1:8100/signals/strategies` deve listar estratÃ©gias
9. API em `http://127.0.0.1:8100/signals/generate` deve gerar sinais explicados
10. Frontend em `http://localhost:5173` deve mostrar badge `PAPER`, overlays, painel OHLC e sinais

## PrÃ³ximas frentes (em paralelo)

- **Paper trading** â€” prÃ³ximo salto de produto (execuÃ§Ã£o simulada live)
- **Feed IBKR robusto** â€” spec em `docs/realtime-data-feed-spec.md` (Nuno)
- **Onboarding Mac/Linux** â€” scripts cross-platform para `npm run dev:all` (sÃ³ Postgres em Docker)

## Fora de escopo (ainda)

- ExecuÃ§Ã£o de ordens reais (live trading)
- IBKR adapter (opcional numa fase futura; nÃ£o bloqueia o feed v1)
