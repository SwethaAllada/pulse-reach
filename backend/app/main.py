import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.engagement import router as engagement_router
from app.api.health import router as health_router
from app.api.population import router as population_router
from app.api.portal import router as portal_router
from app.api.v1 import router as v1_router
from app.core.config import settings
from app.core.errors import INTERNAL_ERROR_MESSAGE, error_body, install_error_handlers
from app.core.logging import configure_logging, request_id_var
from app.core.startup import validate_startup

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
    if settings.startup_validation:
        report = validate_startup(settings)
        logger.info(
            "Startup validation passed (bundle_sha256=%s, rules=%d, authoritative=%d, db_rule_load_id=%s)",
            report.bundle_sha256[:12],
            report.rules,
            report.authoritative_rules,
            report.db_rule_load_id,
        )
    if settings.auth_mode == "users":
        logger.info("Access control: user authentication, RBAC and organization isolation (AUTH_MODE=users)")
        if settings.demo_identity_seed:
            from app.services.identity.demo import seed_demo_identities_at_startup

            seed_demo_identities_at_startup()
    else:
        from app.core.write_auth import write_protection_status

        logger.warning("Access control: AUTH_MODE=legacy (public reads, shared write key); migration only")
        protection = write_protection_status()
        if protection == "enforced":
            logger.info("Write protection: enforced (X-PulseReach-Write-Key)")
        elif protection == "unprotected":
            logger.warning("Write protection: DISABLED by ALLOW_UNPROTECTED_WRITES=true; never use publicly")
        else:
            logger.warning("Write protection: WRITE_API_KEY not set; all state-changing requests are refused")
    from app.services.ai import get_ai_service

    logger.info("AI service: %s", get_ai_service().status())
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=_lifespan)
install_error_handlers(app)


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
        return JSONResponse(
            error_body(500, INTERNAL_ERROR_MESSAGE),
            status_code=500,
            headers={"X-Request-ID": req_id},
        )
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
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(portal_router)
app.include_router(engagement_router)
app.include_router(population_router)
