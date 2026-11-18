import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.core.config import settings

logger = logging.getLogger("pulsereach.startup")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    logger.info(
        "PulseReach API starting (data_source=%s, db_configured=%s)",
        settings.data_source,
        settings.database_url is not None,
    )
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(v1_router)
