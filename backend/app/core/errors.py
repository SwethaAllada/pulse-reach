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
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}
INTERNAL_ERROR_MESSAGE = "Internal server error."
# Localized fallback message per status when the error carries no catalog key.
_STATUS_MESSAGE_KEYS = {401: "auth.not_authenticated", 403: "error.forbidden", 429: "auth.rate_limited"}


def _message(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    return "Request failed."


def error_body(
    status: int,
    detail: Any,
    message: str | None = None,
    *,
    message_key: str | None = None,
    locale: str | None = None,
) -> dict[str, Any]:
    err: dict[str, Any] = {
        "status": status,
        "code": _CODES.get(status, "error"),
        "message": message if message is not None else _message(detail),
        "request_id": request_id_var.get(),
    }
    if message_key is not None:
        err["message_key"] = message_key
    if locale is not None:
        err["locale"] = locale
    return {"detail": detail, "error": err}


def _localized(request: Request, exc: Any) -> tuple[str | None, str | None, str]:
    """(message, message_key, locale) for an HTTP error; message None = keep the default."""
    from app.core.i18n import AppError, resolve_locale, t

    locale = resolve_locale(request)
    if isinstance(exc, AppError):
        return t(exc.message_key, locale, **exc.params), exc.message_key, locale
    key = _STATUS_MESSAGE_KEYS.get(exc.status_code)
    if key is not None and locale != "en":
        return t(key, locale), key, locale
    return None, None, locale


def _validation_detail(exc: RequestValidationError) -> list[dict[str, Any]]:
    # Keep location, message and type; drop echoed input and context objects.
    return [
        {k: e[k] for k in ("type", "loc", "msg") if k in e}
        for e in jsonable_encoder(exc.errors())
    ]


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message, key, locale = _localized(request, exc)
        headers = {**(getattr(exc, "headers", None) or {}), "Content-Language": locale}
        return JSONResponse(
            error_body(
                exc.status_code, exc.detail, message, message_key=key, locale=locale if key else None
            ),
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        from app.core.i18n import resolve_locale, t

        detail = _validation_detail(exc)
        first = detail[0]["msg"] if detail else "Invalid request."
        locale = resolve_locale(request)
        if locale == "en":
            message = f"Invalid request: {first}"
        else:
            where = ".".join(str(p) for p in detail[0]["loc"]) if detail else ""
            message = t("error.validation", locale, reason=where or first)
        return JSONResponse(
            error_body(422, detail, message, message_key="error.validation", locale=locale),
            status_code=422,
            headers={"Content-Language": locale},
        )
