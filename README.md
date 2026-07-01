# App Trading

Plataforma de análise e decisão de trading em modo **PAPER** (sem execução de ordens reais): mercado, sinais, simulação histórica e memória institucional entre runs.

## Estado actual (Jun 2026)

| Área | Disponível |
|------|------------|
| Mercado | Histórico + tempo real (gráfico, indicadores, IBKR stream) |
| Sinais | Histórico + live (`POST /signals/evaluate-live`), overlay no gráfico |
| Simulação | Backtest realista, walk-forward, export CSV, análise crítica por run |
| Memória | Lições e recomendações entre simulações, botão **Aplicar sugestão** |
| Auth | JWT multi-utilizador, combinações de estratégias partilhadas |

Documentação de estado: `docs/status-2026-06-30.md`

## Desenvolvimento em paralelo (prompt-first)

Guia operacional completo:
- `docs/development-environments-prompt-first.md`

Specs de frentes paralelas (AI agents):
- Real-time data feed: `docs/realtime-data-feed-spec.md`
- Plano Backtesting/Simulação: `docs/backtesting-phase-plan.md`

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
- `POST /backtests/run` corre simulação histórica e persiste resultado
- `GET /backtests` lista backtests do utilizador autenticado (com resumo de insight)
- `GET /backtests/lessons` e `GET /backtests/recommendations` — memória institucional
- `POST /signals/evaluate-live` — sinais na vela em formação
- Dashboard com gráfico, overlays, simulação e sinais explicados

## Próxima fase prioritária

**Paper trading em tempo real** — ordens simuladas com base em sinais/consenso, portfolio virtual e PnL intraday. O modo `PAPER` e o motor de backtest já existem; falta a camada de execução simulada live.

Melhorias em curso (memória v2 + UX):
- valores sugeridos exactos nas recomendações (em vez de deltas heurísticos),
- resumo de insight na lista de runs,
- aviso quando dados de mercado estão obsoletos nos sinais live.

Histórico do plano de backtesting (já entregue): `docs/backtesting-phase-plan.md`

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

## Próximas frentes (em paralelo)

- **Paper trading** — próximo salto de produto (execução simulada live)
- **Feed IBKR robusto** — spec em `docs/realtime-data-feed-spec.md` (Nuno)
- **Onboarding Mac/Linux** — scripts cross-platform para `npm run dev:all` (só Postgres em Docker)

## Fora de escopo (ainda)

- Execução de ordens reais (live trading)
- IBKR adapter (opcional numa fase futura; não bloqueia o feed v1)
