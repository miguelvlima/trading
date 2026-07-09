$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
Set-Location $backendDir

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

$pythonExe = ".\.venv\Scripts\python.exe"

& $pythonExe -m pip install -e ".[dev]"

if ((-not (Test-Path ".env")) -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
}

& $pythonExe -m alembic upgrade head
& $pythonExe -m app.scripts.bootstrap_dev_user
# Porta 8100: a 8000 colide com o Docker Desktop (containers de outros projetos
# publicam 0.0.0.0:8000 e o relay WSL segura ::1:8000, apanhando "localhost").
& $pythonExe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8100
