# Trading Backend (Fase 2)

## Requisitos

- Python 3.11+
- PostgreSQL local (via Docker Compose na raiz do projeto)

## Setup rápido

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
copy .env.example .env
```

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
- `GET /market-data/instruments`
- `GET /market-data/bars?symbol=AAPL&timeframe=1d`
- `POST /market-data/import-csv`

## Importar CSV OHLCV

CSV com cabeçalho obrigatório: `timestamp,open,high,low,close,volume`

```powershell
python -m app.scripts.import_ohlcv --symbol AAPL --timeframe 1d --csv-path .\data\aapl.csv
```
