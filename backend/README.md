# Trading Backend (Fase 4)

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
- `GET /market-data/indicators?symbol=AAPL&timeframe=1d`
- `GET /signals/strategies`
- `POST /signals/generate`
- `GET /signals`
- `POST /auth/login`
- `GET /auth/me`
- `GET/POST/PUT /strategy-combinations`

## Importar CSV OHLCV

CSV com cabeçalho obrigatório: `timestamp,open,high,low,close,volume`

```powershell
python -m app.scripts.import_ohlcv --symbol AAPL --timeframe 1d --csv-path .\data\aapl.csv
```
