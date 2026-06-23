from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.backtests import router as backtests_router
from app.api.routes.broker_connections import router as broker_connections_router
from app.api.routes.market_data import router as market_data_router
from app.api.routes.signals import router as signals_router
from app.api.routes.strategy_combinations import router as strategy_combinations_router
from app.api.routes.system import router as system_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("app_started", mode=settings.mode, env=settings.env)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(system_router)
app.include_router(auth_router)
app.include_router(market_data_router)
app.include_router(signals_router)
app.include_router(strategy_combinations_router)
app.include_router(broker_connections_router)
app.include_router(backtests_router)
