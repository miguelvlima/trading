"""GET /system/status — aggregated diagnostics for the Configuração → Sistema panel."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.config import Settings, get_settings
from app.db.dependencies import get_db_session
from app.db.models import User
from app.services.system_diagnostics import run_all_checks, worst_status

router = APIRouter(prefix="/system", tags=["system"])


class SystemCheckResponse(BaseModel):
    key: str
    label: str
    status: str
    detail: str
    hint: str | None = None
    data: dict = {}


class SystemStatusResponse(BaseModel):
    generated_at: datetime
    overall: str
    checks: list[SystemCheckResponse]


@router.get("/status", response_model=SystemStatusResponse)
def get_system_status(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SystemStatusResponse:
    checks = run_all_checks(db, settings)
    return SystemStatusResponse(
        generated_at=datetime.now(UTC),
        overall=worst_status(checks),
        checks=[SystemCheckResponse(**check.__dict__) for check in checks],
    )
