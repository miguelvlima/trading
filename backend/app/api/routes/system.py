from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str


class ModeResponse(BaseModel):
    mode: str


@router.get("/health", response_model=HealthResponse, tags=["system"])
def get_health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/mode", response_model=ModeResponse, tags=["system"])
def get_mode() -> ModeResponse:
    settings = get_settings()
    return ModeResponse(mode=settings.mode.upper())
