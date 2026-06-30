# Real-Time Market Data Feed — Spec oficial (Fase paralela)

Este documento é a **fonte de verdade** para a frente de **Dados Reais + Tempo Real**.

Branch de trabalho: `feature/realtime-data-feed-v1` (a partir de `develop`).

Owner: Nuno (real-time data).  
Paralelo a: Backtesting/Simulação (Miguel, branch `feature/backtesting-simulation-v1` ou equivalente em `develop`).

---

## Objetivo

Ligar a aplicação a **dados de mercado reais** e mantê-los **atualizados em tempo (quase) real**, persistindo candles normalizados na base de dados existente (`instruments`, `market_bars`).

O provider **default** desta fase é o **IBKR** (via IB Gateway / TWS API, em modo paper read-only — apenas market data, sem execução de ordens). A camada de provider é uma abstração, por isso ficam suportados providers REST/polling alternativos (ex.: **yfinance** como fallback para dev/CI sem Gateway), mas o default e o caminho principal é IBKR.

---

## Baseline do repositório (o que já existe)

Antes de implementar, assumir este estado real do projeto:

| Área | O que existe hoje |
| --- | --- |
| Backend | FastAPI em `backend/app/` |
| Config | `backend/app/core/config.py` |
| Models | `Instrument`, `MarketBar` em `backend/app/db/models.py` |
| Dados históricos | CSV import + consulta via `backend/app/api/routes/market_data.py` |
| Serviços | `csv_importer.py`, `indicator_engine.py`, `strategy_engine.py` |
| Auth | JWT em `backend/app/api/routes/auth.py` |
| Frontend | Monolítico: `frontend/src/App.tsx` + `styles.css` (4 ficheiros) |
| Testes | ~23 testes em `backend/tests/` (9 ficheiros) |

Endpoints históricos já usados pelo resto da app:

- `GET /market-data/instruments`
- `GET /market-data/bars?symbol=&timeframe=&limit=`
- `GET /market-data/indicators?symbol=&timeframe=`
- `POST /market-data/import-csv`

**Não existem ainda** módulos de feed em tempo real, WebSocket, nem adapter de broker. Isso é **normal** — faz parte desta entrega.

---

## Entregáveis desta fase (a implementar)

Implementar os componentes abaixo **neste repo**, respeitando convenções existentes.

### 1) Camada de provider (adapter)

Criar abstração de provider de mercado:

- `backend/app/services/data_feed/types.py`
  - dataclass `BarQuote` (ou equivalente): `symbol`, `timestamp`, `open`, `high`, `low`, `close`, `volume`
  - interface/protocol `MarketDataProvider` com métodos mínimos:
    - `fetch_latest_quote(symbol: str) -> BarQuote | None`
    - `fetch_recent_bars(symbol: str, timeframe: str, limit: int) -> list[BarQuote]`

- `backend/app/services/data_feed/providers/ibkr_provider.py` (**default**)
  - implementação concreta via IB Gateway / TWS (`ib_insync`), com reconexão/backoff, timeouts e rate-limit básico; normaliza tudo para UTC e marca `is_final`.

Fallback (selecionável via `REALTIME_FEED_PROVIDER=yfinance`):

- `backend/app/services/data_feed/providers/yfinance_provider.py` — provider REST/polling, sem necessidade de Gateway (útil para dev/CI).

### 2) Serviço de ingestão e normalização

- `backend/app/services/data_feed/service.py`
  - responsável por:
    - garantir `Instrument` existe (criar se necessário),
    - normalizar quotes/bars para o schema `MarketBar`,
    - upsert idempotente (respeitar unique constraint por `instrument_id + timeframe + timestamp`),
    - expor estado do feed (última atualização, lag, erros recentes).

### 3) Throttling / pacing

- `backend/app/services/data_feed/pacing.py`
  - classe `PacingThrottle` (intervalo mínimo entre requests, backoff simples).
  - evitar ban/rate-limit do provider.

### 4) API de real-time (novos endpoints)

Criar router:

- `backend/app/api/routes/realtime_data.py`
- prefixo recomendado: `/realtime`

Endpoints mínimos:

| Método | Path | Descrição |
| --- | --- | --- |
| GET | `/realtime/health` | estado do feed (running/stale/error, last_update, provider) |
| GET | `/realtime/quote?symbol=AAPL` | última quote normalizada |
| GET | `/realtime/history?symbol=AAPL&timeframe=1d&limit=100` | histórico recente via provider (opcional v1, útil para debug) |

Todos protegidos com `get_current_user` (mesmo padrão de `market_data.py`).

Registar router em `backend/app/main.py` (PR pequena, avisar se houver conflito).

### 5) Worker / script contínuo

- `backend/app/scripts/run_realtime_feed.py`

Comportamento:

- loop de polling configurável (símbolos, timeframe, intervalo),
- chama `data_feed/service.py` para persistir bars,
- logs estruturados (structlog, como resto do backend),
- paragem limpa com Ctrl+C.

Variáveis sugeridas em `backend/.env.example`:

- `REALTIME_FEED_PROVIDER=ibkr`
- `REALTIME_FEED_SYMBOLS=AAPL,MSFT,NVDA`
- `REALTIME_FEED_TIMEFRAME=1d`
- `REALTIME_FEED_POLL_SECONDS=60`
- `REALTIME_FEED_STALE_AFTER_SECONDS=180`
- `IBKR_GATEWAY_HOST=127.0.0.1`
- `IBKR_GATEWAY_PORT=4002`
- `IBKR_CLIENT_ID=7`

### 6) Testes

Criar:

- `backend/tests/fakes.py` — fake provider determinístico para testes
- `backend/tests/test_realtime_data_endpoints.py`
- `backend/tests/test_data_feed_service.py`

Cobrir:

- health endpoint,
- quote endpoint,
- persistência/upsert em `market_bars`,
- throttle básico,
- user-scoping/auth (401 sem token).

### 7) Documentação operacional

Atualizar `backend/README.md` com:

- como arrancar o worker localmente,
- variáveis de ambiente,
- smoke test dos novos endpoints.

---

## Contrato de dados (não quebrar)

Manter compatibilidade com o resto da app:

- `symbol`: uppercase, max 32 chars
- `timeframe`: string livre curta (`1d`, `1h`, `5m`, etc.)
- `timestamp`: timezone-aware (UTC)
- OHLCV: `Numeric` compatível com modelos existentes
- **Não alterar** breaking fields de `market_bars` sem acordo explícito

A simulação/backtesting e os sinais continuam a ler `market_bars` — o feed real-time alimenta a mesma tabela.

---

## Fronteiras de ownership (evitar conflitos)

### Domínio Nuno (real-time) — pode criar/editar

- `backend/app/services/data_feed/**`
- `backend/app/api/routes/realtime_data.py`
- `backend/app/scripts/run_realtime_feed.py`
- `backend/tests/fakes.py`
- `backend/tests/test_realtime_data_*`
- `backend/tests/test_data_feed_*`
- docs desta frente

### Domínio Miguel (backtesting) — não tocar

- `backend/app/services/backtest_engine.py`
- `backend/app/api/routes/backtests.py`
- `backend/app/schemas/backtests.py`
- `backend/tests/test_backtests_endpoints.py`
- migrations de backtest
- `frontend/src/App.tsx` (secção Simulação)
- `frontend/src/styles.css` (estilos de backtest)

### Ficheiros sensíveis — PR pequena + aviso prévio

- `backend/app/db/models.py` (só se schema novo for mesmo necessário; preferir reutilizar `MarketBar`)
- `backend/app/main.py` (registar router)
- `README.md`, `backend/README.md`

---

## Fora de escopo

- Execução de ordens reais (IBKR fica em paper / read-only — só market data)
- Substituir endpoints históricos `/market-data/*`

> Nota: o **WebSocket de ticks** e o **refactor do frontend em componentes/hooks
> isolados + indicadores** estavam fora de escopo na v1 e passaram a ser
> entregues na **v2** (ver secção abaixo).

---

## Critérios de done (v1)

- [x] Branch `feature/realtime-data-feed-v1` baseada em `develop` atualizado
- [x] Provider + service + pacing implementados
- [x] Endpoints `/realtime/health`, `/realtime/quote` (e opcional `/realtime/history`)
- [x] Script `run_realtime_feed.py` persiste bars em `market_bars`
- [x] Testes novos passam; suite existente sem regressões (`pytest`)
- [x] `backend/README.md` atualizado com runbook do feed
- [x] PR para `develop` com evidência de testes

---

## v2 — Tempo real por WebSocket + UI rica

Branch: `feature/realtime-tab-ws-v2` (a partir de `develop`). A v2 mantém o
contrato e os endpoints da v1 e acrescenta streaming push e uma aba reconstruída.
**A aba Realtime vive dentro de `App.tsx` (ficheiro partilhado) — só o ponto de
entrada que renderiza `<RealtimePage>` é tocado; toda a lógica vive em
`frontend/src/realtime/`.**

### Backend

- **WebSocket `/realtime/ws`** (`api/routes/realtime_ws.py`): JWT validado no
  handshake (token na query string), bridge de um `StreamingProvider` para o
  socket via uma fila + tarefa única de envio. Mensagens cliente→servidor
  `{"action":"subscribe","symbol":...}`; servidor→cliente `tick` / `index` /
  `subscribed` / `error`.
- **Três canais** (`providers/ibkr_provider.py::IBKRStreamingProvider`, em thread
  com event-loop próprio): ticks (`reqMktData`), barras em formação
  (`keepUpToDate`) e índices (`Index(...)`/`Forex`).
- **Gestão do teto de ~100 linhas** (`data_feed/streaming.py::SubscriptionManager`):
  conta as subscrições ativas e cancela (`cancelMktData`) a linha anterior ao
  trocar de símbolo — sem subscrições órfãs. Degrada com mensagem clara se o teto
  for atingido.
- **Paginação histórica throttled** (`fetch_history_paginated`): a janela "All"
  pagina recuando `endDateTime`, **cada página pelo `PacingThrottle`**.
- **Contrato crítico mantido**: a barra **em formação** (`is_final=False`) é
  estado efémero de stream/UI e **nunca** é escrita em `market_bars`; só barras
  fechadas são persistidas. Timestamps sempre UTC do servidor/IBKR.
- Endpoints REST novos: `GET /realtime/history?...&window=` (paginado) e
  `GET /realtime/indices`. Settings: `REALTIME_MAX_MARKET_DATA_LINES`,
  `IBKR_MARKET_DATA_TYPE` (1 live / 3 delayed p/ paper).

### Frontend (`frontend/src/realtime/`)

- `RealtimePage` orquestrador; `SymbolBar`, `ChartControls` (híbrido janela↔vela
  com sugestão/override manual), `LiveDataPanel` (stream por tick, flash),
  `LastBarPanel` (SNAPSHOT vs EM FORMAÇÃO), `IndexStrip`.
- `useTickStream` (WebSocket), `useBars` (history por janela), `CandleChart`
  estendido (overlays + panes de osciladores + barra em formação + chart-head).
- `indicators/`: módulos puros e testáveis — SMA, EMA, WMA, VWAP, Bollinger
  (overlays) e RSI, MACD, ATR, Stochastic, ADX, OBV (osciladores).
- CSS confinado a `realtime.css` (tokens em `.rt-page`), sem afetar a barra de
  abas nem a Simulação.

### Testes (offline, sem Gateway)

- `tests/test_subscription_manager.py` — teto de linhas + cancel-on-switch.
- `tests/test_realtime_ws.py` — handshake JWT, stream de ticks/índices,
  cancelamento ao trocar símbolo, degradação no teto (via `FakeStreamingProvider`).
- `tests/test_realtime_data_endpoints.py` — `/realtime/indices` + fallback do
  `window`.

---

## Prompt para agente AI (copy/paste)

```text
Repository: https://github.com/miguelvlima/trading
Branch: create feature/realtime-data-feed-v1 from develop (git pull first).

Read and follow exactly:
- docs/realtime-data-feed-spec.md (source of truth for this task)
- docs/development-environments-prompt-first.md (workflow/CI/migrations)

Task: implement Real-Time Market Data Feed v1 as defined in the spec.

Important interpretation rules:
1) Files listed in the spec (adapter, types, service, pacing, fakes, realtime endpoints) are DELIVERABLES TO BUILD — they do not exist yet and that is expected.
2) Reuse existing models Instrument/MarketBar and existing auth pattern (get_current_user).
3) Do NOT refactor unrelated modules (backtests, signals UI, broker_connections).
4) Default provider is IBKR (IB Gateway / TWS, paper read-only, market data only); yfinance stays as a selectable REST fallback for dev/CI without a Gateway.
5) Keep /market-data/* endpoints backward compatible.

Deliverables:
- backend/app/services/data_feed/ (types, pacing, provider, service)
- backend/app/api/routes/realtime_data.py
- backend/app/scripts/run_realtime_feed.py
- backend/tests/fakes.py + tests for service/endpoints
- register router in main.py
- update backend/README.md

Validation before PR:
- cd backend && pytest
- cd frontend && npm run build (should remain green even if frontend unchanged)
- if schema changed: alembic heads (single head) + alembic upgrade head

Open PR to develop with test evidence. Do not push to main/develop directly.
```
