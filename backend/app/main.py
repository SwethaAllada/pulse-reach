import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.core.config import settings
from app.core.logging import configure_logging, request_id_var

configure_logging(settings.log_level)
logger = logging.getLogger("pulsereach.startup")
http_logger = logging.getLogger("pulsereach.http")
_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    logger.info(
        "PulseReach API starting (data_source=%s, db_configured=%s, llm_enabled=%s)",
        settings.data_source,
        settings.database_url is not None,
        settings.llm_enabled,
    )
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=_lifespan)


@app.middleware("http")
async def request_id_and_logging_middleware(request: Request, call_next):
    incoming_id = request.headers.get("X-Request-ID")
    req_id = (
        incoming_id
        if incoming_id and _SAFE_REQUEST_ID_RE.match(incoming_id)
        else uuid.uuid4().hex
    )
    token = request_id_var.set(req_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = req_id
        http_logger.info(
            "HTTP request completed",
            extra={
                "request_id": req_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        http_logger.exception(
            "HTTP request failed",
            extra={
                "request_id": req_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": duration_ms,
            },
        )
        raise
    finally:
        request_id_var.reset(token)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(v1_router)
