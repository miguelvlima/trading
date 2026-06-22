# Trading Backend (Fase 1)

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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Testes

```powershell
pytest
```

## Endpoints iniciais

- `GET /health` -> `{"status":"ok"}`
- `GET /mode` -> `{"mode":"PAPER"}`
