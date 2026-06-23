# Trading Backend (Fase 4)

## Requisitos

- Python 3.11+
- PostgreSQL local (via Docker Compose na raiz do projeto)

## Ambientes e workflow da equipa

Consulte o guia completo para trabalho em paralelo (prompt-first):
- `../docs/development-environments-prompt-first.md`
- Inclui runbook de deploy para staging e production com smoke tests.

Spec da frente real-time (Nuno):
- `../docs/realtime-data-feed-spec.md`

Templates de ambiente:
- local: `backend/.env.example`
- staging: `backend/.env.staging.example`
- production: `backend/.env.production.example`

## Setup rápido

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
copy .env.example .env
```

No arranque local via script central (`npm run dev:all` na raiz), o backend executa:
- `alembic upgrade head`
- `python -m app.scripts.bootstrap_dev_user`

Isto cria automaticamente (se não existir) um user local:
- email: `dev@tradingapp.dev`
- password: `DevPass123!`

## Segurança mínima (recomendado para partilha)

No `backend/.env`, define:

- `CORS_ALLOW_ORIGINS=http://localhost:5173,https://<teu-frontend>.vercel.app`
- `JWT_SECRET_KEY=<chave-forte>`

Nesta fase o registo público está desativado. Crie utilizadores internos via script:

```powershell
python -m app.scripts.create_user --email admin@empresa.com --password "StrongPass123" --display-name "Admin"
```

Os endpoints de `market-data`, `signals` e `strategy-combinations` exigem sessão com token Bearer.

## Operação em produção (hardening)

- Não use bootstrap automático de admin no startup.
- Não mantenha variáveis `BOOTSTRAP_ADMIN_*` definidas em produção.
- Para criar utilizadores internos, execute apenas o script administrativo manual:

```powershell
python -m app.scripts.create_user --email user@empresa.com --password "StrongPass123" --display-name "Nome"
```

### Smoke test rápido pós-deploy

```powershell
curl https://<backend>.up.railway.app/health
```

```powershell
curl -X POST https://<backend>.up.railway.app/auth/login -H "Content-Type: application/json" -d "{\"email\":\"user@empresa.com\",\"password\":\"StrongPass123\"}"
```

### Guardrails de migrations (trabalho paralelo)

Antes de abrir PR com alterações de schema:

```powershell
alembic heads
```

O resultado deve indicar apenas um head ativo.

## Arrancar backend

```powershell
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Testes

```powershell
pytest
```

## Endpoints iniciais

- `GET /health` -> `{"status":"ok"}`
- `GET /mode` -> `{"mode":"PAPER"}`
- `GET /version` -> `{"version":"0.1.0"}`
- `GET /market-data/instruments`
- `GET /market-data/bars?symbol=AAPL&timeframe=1d`
- `POST /market-data/import-csv`
- `GET /market-data/indicators?symbol=AAPL&timeframe=1d`
- `GET /realtime/health`
- `GET /realtime/quote?symbol=AAPL`
- `GET /realtime/history?symbol=AAPL&timeframe=1d&limit=100`
- `GET /signals/strategies`
- `POST /signals/generate`
- `GET /signals`
- `POST /backtests/run`
- `GET /backtests`
- `GET /backtests/{id}`
- `POST /auth/login`
- `GET /auth/me`
- `GET/POST/PUT /strategy-combinations`
- `GET/POST/PUT/DELETE /broker-connections`

## Importar CSV OHLCV

CSV com cabeçalho obrigatório: `timestamp,open,high,low,close,volume`

```powershell
python -m app.scripts.import_ohlcv --symbol AAPL --timeframe 1d --csv-path .\data\aapl.csv
```

## Feed de dados em tempo real (Real-Time Market Data Feed)

Liga a app a dados de mercado reais via polling de um provider REST (`yfinance` por
omissão) e persiste candles normalizados na tabela existente `market_bars` (reutiliza
`Instrument` / `MarketBar`, sem alterações de schema).

### Variáveis de ambiente

Definidas em `backend/.env` (ver `.env.example`):

| Variável | Default | Descrição |
| --- | --- | --- |
| `REALTIME_FEED_PROVIDER` | `yfinance` | Provider de mercado a usar |
| `REALTIME_FEED_SYMBOLS` | `AAPL,MSFT,NVDA` | Símbolos a seguir (separados por vírgula) |
| `REALTIME_FEED_TIMEFRAME` | `1d` | Timeframe dos candles |
| `REALTIME_FEED_POLL_SECONDS` | `60` | Intervalo entre ciclos de polling |
| `REALTIME_FEED_STALE_AFTER_SECONDS` | `120` | Lag acima do qual o feed é considerado `stale` |
| `REALTIME_FEED_MIN_REQUEST_INTERVAL_SECONDS` | `1.0` | Pacing mínimo entre requests ao provider |

### Arrancar o worker localmente

```powershell
# a partir de backend/, com o venv ativo e a DB acessível
python -m app.scripts.run_realtime_feed
```

O worker faz polling de cada símbolo, normaliza para o schema `MarketBar` e faz upsert
idempotente (constraint `instrument_id + timeframe + timestamp`). Para parar, `Ctrl+C`
(paragem limpa).

### Smoke test dos endpoints

Todos os endpoints exigem token Bearer (`get_current_user`):

```powershell
$token = (curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"email\":\"dev@tradingapp.dev\",\"password\":\"DevPass123!\"}" | ConvertFrom-Json).access_token

curl http://localhost:8000/realtime/health -H "Authorization: Bearer $token"
curl "http://localhost:8000/realtime/quote?symbol=AAPL" -H "Authorization: Bearer $token"
curl "http://localhost:8000/realtime/history?symbol=AAPL&timeframe=1d&limit=100" -H "Authorization: Bearer $token"
```

- `GET /realtime/health` — estado do feed (`running` / `stale` / `empty`), `last_update`, `lag_seconds`, provider, símbolos seguidos.
- `GET /realtime/quote?symbol=AAPL` — última quote normalizada (read-through ao provider).
- `GET /realtime/history?symbol=AAPL&timeframe=1d&limit=100` — histórico recente via provider (útil para debug).
