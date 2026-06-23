# App Trading - Fase 4

Scaffold da aplicação com backend FastAPI, frontend React/Vite, PostgreSQL via Docker Compose, indicadores técnicos e geração de sinais por estratégia.

## Desenvolvimento em paralelo (prompt-first)

Guia operacional completo:
- `docs/development-environments-prompt-first.md`

Convenção de branches:
- `main`: produção
- `develop`: integração/staging
- `feature/<tema>`: trabalho por tarefa
- `hotfix/<tema>`: correções urgentes de produção

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
- `GET /version` devolve a versão da API
- `GET /market-data/instruments` lista instrumentos
- `GET /market-data/bars` consulta candles por símbolo/timeframe
- `POST /market-data/import-csv` importa CSV OHLCV para PostgreSQL
- `GET /market-data/indicators` calcula indicadores técnicos
- `GET /signals/strategies` lista estratégias disponíveis
- `POST /signals/generate` gera e persiste sinais por estratégia
- `GET /signals` lista sinais persistidos
- Dashboard com gráfico, overlays e painel de sinais explicados

## Como arrancar

### Opção rápida (recomendado)

Na raiz do projeto, arranca DB + backend + frontend com um único comando:

```powershell
npm install
npm run dev:all
```

O arranque local automático também cria (se não existir) um utilizador dev no backend:
- email: `dev@tradingapp.dev`
- password: `DevPass123!`

Estas credenciais são apenas para `ENV=dev` e podem ser alteradas em `backend/.env` via:
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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Variáveis relevantes no `backend/.env`:

- `CORS_ALLOW_ORIGINS` (ex: `http://localhost:5173,https://trading-kappa-dusky.vercel.app`)
- `JWT_SECRET_KEY` (obrigatório para assinatura dos tokens)

Criação de utilizador interno (registo público desativado):

```powershell
cd backend
.\.venv\Scripts\python -m app.scripts.create_user --email admin@empresa.com --password "StrongPass123" --display-name "Admin"
```

Nota: em desenvolvimento local via `npm run dev:all`, o bootstrap automático já cria o user dev default.

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

Variáveis relevantes no `frontend/.env`:

- `VITE_API_BASE_URL` (URL pública do backend)

## Validação manual rápida

1. API em `http://localhost:8000/health` deve devolver `{"status":"ok"}`
2. API em `http://localhost:8000/mode` deve devolver `{"mode":"PAPER"}`
3. API em `http://localhost:8000/version` deve devolver `{"version":"0.1.0"}`
4. Importar um CSV e validar resposta com linhas importadas
5. API em `http://localhost:8000/market-data/instruments` deve listar o símbolo importado
6. API em `http://localhost:8000/market-data/bars?symbol=AAPL&timeframe=1d` deve devolver candles
7. API em `http://localhost:8000/market-data/indicators?symbol=AAPL&timeframe=1d` deve devolver indicadores
8. API em `http://localhost:8000/signals/strategies` deve listar estratégias
9. API em `http://localhost:8000/signals/generate` deve gerar sinais explicados
10. Frontend em `http://localhost:5173` deve mostrar badge `PAPER`, overlays, painel OHLC e sinais

## Fora de escopo nesta fase

- IBKR adapter/conectividade
- Sinais/estratégias
- Backtesting
- Preparação/confirmação de ordens
