# App Trading - Fase 1

Base inicial do projeto com backend FastAPI, frontend React/Vite e PostgreSQL via Docker Compose.

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
- Dashboard vazio com banner `PAPER` visível

## Como arrancar

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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
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
3. Frontend em `http://localhost:5173` deve mostrar badge `PAPER`

## Fora de escopo nesta fase

- IBKR adapter/conectividade
- Sinais/estratégias
- Backtesting
- Preparação/confirmação de ordens
