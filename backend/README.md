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
- Plano funcional Backtesting/Simulação:
- `../docs/backtesting-phase-plan.md`

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

Liga a app a dados de mercado reais via polling de um provider e persiste candles
normalizados na tabela existente `market_bars` (reutiliza `Instrument` / `MarketBar`,
sem alterações de schema).

Providers disponíveis:
- `ibkr` (**default**) — via IB Gateway / TWS API (paper, read-only). Requer um IB Gateway
  a correr (ver pré-requisitos abaixo). `ib_insync` já vem nas dependências base.
- `yfinance` (fallback) — REST/polling, sem necessidade de Gateway. Selecionar com
  `REALTIME_FEED_PROVIDER=yfinance` (útil para dev/CI sem IBKR).

### Contrato de dados (importante)

- **Só barras fechadas (`is_final`)**: a barra do período ainda em formação (ex.: a barra
  `1d` de hoje a meio do dia) **não** é persistida. Assim o backtesting nunca lê um `close`
  que ainda vai mudar. O serviço (`data_feed/service.py`) descarta `is_final=False`.
- **Time-source = servidor, em UTC**: os timestamps das barras vêm do provider normalizados
  a UTC, nunca de `datetime.now()` local (o relógio da máquina não é de confiança —
  ver nota do IB Gateway abaixo). `now()` só é usado para decidir se um período já fechou.
- **Upsert idempotente**: respeita a constraint `instrument_id + timeframe + timestamp`; o
  get-or-create de `Instrument` trata `IntegrityError` (corrida com o importador de CSV).

### Variáveis de ambiente

Definidas em `backend/.env` (ver `.env.example`):

| Variável | Default | Descrição |
| --- | --- | --- |
| `REALTIME_FEED_PROVIDER` | `ibkr` | Provider de mercado (`ibkr` default, ou `yfinance`) |
| `REALTIME_FEED_SYMBOLS` | `AAPL,MSFT,NVDA` | Símbolos a seguir (separados por vírgula) |
| `REALTIME_FEED_TIMEFRAME` | `1d` | Timeframe dos candles |
| `REALTIME_FEED_POLL_SECONDS` | `60` | Intervalo entre ciclos de polling |
| `REALTIME_FEED_STALE_AFTER_SECONDS` | `180` | Lag acima do qual o feed é considerado `stale` |
| `REALTIME_FEED_MIN_REQUEST_INTERVAL_SECONDS` | `1.0` | Pacing mínimo entre requests ao provider |
| `IBKR_GATEWAY_HOST` | `127.0.0.1` | Host do IB Gateway (só provider `ibkr`) |
| `IBKR_GATEWAY_PORT` | `4002` | Porta do IB Gateway (paper API = `4002`) |
| `IBKR_CLIENT_ID` | `7` | Client ID da ligação à API |

### Pré-requisitos do IB Gateway (provider `ibkr`, default)

Como o `ibkr` é o provider default, o worker e os endpoints `/realtime/quote|history`
precisam de um IB Gateway acessível. (`ib_insync` já está nas dependências base.)

1. Arrancar o **IB Gateway** em modo **paper**.
2. Em *API → Settings*: ativar *Enable ActiveX and Socket Clients*, manter **Read-Only API**
   ligado, e confirmar a porta **4002** (paper).
3. Adicionar `127.0.0.1` aos **Trusted IPs**.

> Sem Gateway acessível, o provider IBKR regista um erro estruturado e devolve vazio/None
> (não rebenta o worker), e o `/realtime/health` reporta `error`/`stale`. Para dev/CI sem
> IBKR, define `REALTIME_FEED_PROVIDER=yfinance`.

> **Nota de fiabilidade**: o IB Gateway pode cair e reconectar silenciosamente
> (`DISCONNECT_ON_INACTIVITY`, `Connection reset`, `HOT_RESTART`), e o relógio do sistema
> pode ser ajustado (`SYSTEM CLOCK HAS BEEN CHANGED...`). Por isso o `/realtime/health`
> mede **staleness** (idade da última barra persistida) e não apenas o estado do socket,
> e os timestamps vêm sempre do servidor em UTC. O worker e o provider IBKR reconectam com
> backoff e nunca morrem ao primeiro erro de ligação.

### Arrancar o worker localmente

```powershell
# a partir de backend/, com o venv ativo e a DB acessível
python -m app.scripts.run_realtime_feed
```

O worker faz polling de cada símbolo, normaliza para o schema `MarketBar` e faz upsert
idempotente **apenas de barras fechadas**. Para parar, `Ctrl+C` (paragem limpa; fecha a
ligação ao Gateway se aplicável).

### Smoke test dos endpoints

Todos os endpoints exigem token Bearer (`get_current_user`):

```powershell
$token = (curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"email\":\"dev@tradingapp.dev\",\"password\":\"DevPass123!\"}" | ConvertFrom-Json).access_token

curl http://localhost:8000/realtime/health -H "Authorization: Bearer $token"
curl "http://localhost:8000/realtime/quote?symbol=AAPL" -H "Authorization: Bearer $token"
curl "http://localhost:8000/realtime/history?symbol=AAPL&timeframe=1d&limit=100" -H "Authorization: Bearer $token"
```

- `GET /realtime/health` — estado por **staleness** (`running` / `stale` / `error` / `empty`), `last_update` (UTC), `lag_seconds` (idade da última barra), `provider`, símbolos seguidos e últimos erros.
- `GET /realtime/quote?symbol=AAPL` — última quote normalizada (read-through ao provider).
- `GET /realtime/history?symbol=AAPL&timeframe=1d&limit=100` — histórico recente via provider (útil para debug).
- `GET /realtime/history?symbol=AAPL&timeframe=5m&window=4h` — histórico por **janela** (1H..All): usa a paginação throttled do IBKR quando disponível, com fallback para `limit`.
- `GET /realtime/indices` — descritores da faixa de índices (valores ao vivo chegam pelo WebSocket).

### WebSocket de ticks (`/realtime/ws`) — v2

Stream push de ticks ao vivo + valores dos índices para a aba Realtime.

- **Auth no handshake**: o token JWT vai na query string (o handshake WS não leva
  header `Authorization`): `ws://localhost:8000/realtime/ws?token=<jwt>`.
- **Cliente → servidor**: `{"action":"subscribe","symbol":"AAPL"}` (troca de
  símbolo), `{"action":"unsubscribe"}`, `{"action":"ping"}`.
- **Servidor → cliente**: `tick` (last/bid/ask/sizes/volume/high/low do dia),
  `index` (símbolo, nome, last, change_pct), `subscribed` (ack + nº de linhas
  ativas), `error` (ex.: `line_budget`).
- **Teto de linhas**: cada símbolo seguido e cada índice consome uma linha
  `reqMktData`; ao trocar de símbolo a linha anterior é cancelada
  (`REALTIME_MAX_MARKET_DATA_LINES`, default 100).
- **Paper sem dados live**: `IBKR_MARKET_DATA_TYPE=3` (delayed) faz o feed receber
  ticks atrasados em vez de nada.
- A **barra em formação** é mostrada no chart/UI mas **nunca** é persistida em
  `market_bars` (só barras fechadas são gravadas).

Smoke test do WebSocket (com `websocat` ou equivalente):

```bash
websocat "ws://localhost:8000/realtime/ws?token=$token"
# depois de ligado, enviar:
{"action":"subscribe","symbol":"AAPL"}
```
