# App Trading - Fase 3

Scaffold da aplicação com backend FastAPI, frontend React/Vite, PostgreSQL via Docker Compose, ingestão de dados históricos OHLCV e indicadores técnicos.

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
- `GET /market-data/instruments` lista instrumentos
- `GET /market-data/bars` consulta candles por símbolo/timeframe
- `POST /market-data/import-csv` importa CSV OHLCV para PostgreSQL
- `GET /market-data/indicators` calcula indicadores técnicos
- Dashboard com gráfico de candles, overlays e painel OHLC no cursor

## Como arrancar

### Opção rápida (recomendado)

Na raiz do projeto, arranca DB + backend + frontend com um único comando:

```powershell
npm install
npm run dev:all
```

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
npm run dev -- --host 0.0.0.0 --port 5173
```

## Validação manual rápida

1. API em `http://localhost:8000/health` deve devolver `{"status":"ok"}`
2. API em `http://localhost:8000/mode` deve devolver `{"mode":"PAPER"}`
3. Importar um CSV e validar resposta com linhas importadas
4. API em `http://localhost:8000/market-data/instruments` deve listar o símbolo importado
5. API em `http://localhost:8000/market-data/bars?symbol=AAPL&timeframe=1d` deve devolver candles
6. API em `http://localhost:8000/market-data/indicators?symbol=AAPL&timeframe=1d` deve devolver indicadores
7. Frontend em `http://localhost:5173` deve mostrar badge `PAPER`, overlays e painel OHLC

## Fora de escopo nesta fase

- IBKR adapter/conectividade
- Sinais/estratégias
- Backtesting
- Preparação/confirmação de ordens
