"""Structured, safe API error responses (BE-24).

Every error body keeps FastAPI's `detail` (existing clients rely on it) and adds
`error = {status, code, message, request_id}`. Messages never contain stack traces, SQL or
bound parameters; unexpected exceptions are logged server-side and returned as a generic 500.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    500: "internal_error",
    503: "service_unavailable",
}
INTERNAL_ERROR_MESSAGE = "Internal server error."


def error_body(status: int, detail: Any, message: str | None = None) -> dict[str, Any]:
    return {
        "detail": detail,
        "error": {
            "status": status,
            "code": _CODES.get(status, "error"),
            "message": message if message is not None else (detail if isinstance(detail, str) else "Request failed."),
            "request_id": request_id_var.get(),
        },
    }


def _validation_detail(exc: RequestValidationError) -> list[dict[str, Any]]:
    # Keep location, message and type; drop echoed input and context objects.
    return [
        {k: e[k] for k in ("type", "loc", "msg") if k in e}
        for e in jsonable_encoder(exc.errors())
    ]


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            error_body(exc.status_code, exc.detail),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = _validation_detail(exc)
        first = detail[0]["msg"] if detail else "Invalid request."
        return JSONResponse(error_body(422, detail, f"Invalid request: {first}"), status_code=422)
