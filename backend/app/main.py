from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.backtests import router as backtests_router
from app.api.routes.broker_connections import router as broker_connections_router
from app.api.routes.market_data import router as market_data_router
from app.api.routes.market_scanner import router as market_scanner_router
from app.api.routes.paper_trading import router as paper_trading_router
from app.api.routes.paper_ws import router as paper_ws_router
from app.api.routes.realtime_data import router as realtime_data_router
from app.api.routes.realtime_ws import router as realtime_ws_router
from app.api.routes.signals import router as signals_router
from app.api.routes.strategy_combinations import router as strategy_combinations_router
from app.api.routes.system import router as system_router
from app.api.routes.system_status import router as system_status_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.paper_trading.runtime import registry, resume_running_engines

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("app_started", mode=settings.mode, env=settings.env)
    resumed = await resume_running_engines(settings)
    if resumed:
        logger.info("paper_engines_resumed", portfolio_ids=resumed)
    yield
    await registry.stop_all()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(system_router)
app.include_router(system_status_router)
app.include_router(auth_router)
app.include_router(market_data_router)
app.include_router(market_scanner_router)
app.include_router(realtime_data_router)
app.include_router(realtime_ws_router)
app.include_router(signals_router)
app.include_router(strategy_combinations_router)
app.include_router(broker_connections_router)
app.include_router(backtests_router)
app.include_router(paper_trading_router)
app.include_router(paper_ws_router)
