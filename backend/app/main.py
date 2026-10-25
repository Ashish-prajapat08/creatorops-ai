import logging
import time
import uuid

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.v1 import intelligence, operations, reconciliation, workspace
from app.api.v1.entities import routers
from app.core.config import settings
from app.core.database import engine
from app.core.errors import AppError
from app.core.logging import setup_logging
from app.core.observability import initialize

cfg = settings()
setup_logging()
initialize()

app = FastAPI(title="CreatorOps AI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[cfg.frontend_url],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Agency-ID"],
    expose_headers=["X-Request-ID"],
)
app.include_router(workspace.router, prefix="/api/v1")
app.include_router(intelligence.router, prefix="/api/v1")
app.include_router(reconciliation.router, prefix="/api/v1")
app.include_router(operations.router, prefix="/api/v1")
for router in routers:
    app.include_router(router, prefix="/api/v1")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex
    started = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    logging.getLogger("creatorops").info(
        "request_completed",
        extra={
            "request_id": request.state.request_id,
            "status": response.status_code,
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return response


def error_response(request, code, message, status, details=None):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", None),
                **({"details": details} if details else {}),
            }
        },
    )


@app.exception_handler(AppError)
async def application_error(request, exc):
    return error_response(request, exc.code, exc.message, exc.status)


@app.exception_handler(RequestValidationError)
@app.exception_handler(ValidationError)
async def validation_error(request, exc):
    # Never serialize submitted values (they could be OAuth codes or secrets).
    details = [
        {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
        for item in exc.errors()
    ]
    return error_response(request, "VALIDATION_ERROR", "Check the submitted fields", 422, details)


@app.exception_handler(IntegrityError)
async def conflict(request, exc):
    return error_response(request, "CONFLICT", "A conflicting record already exists", 409)


@app.exception_handler(Exception)
async def unexpected(request, exc):
    sentry_sdk.capture_exception(exc)
    logging.getLogger("creatorops").error(
        "request_failed",
        extra={"request_id": getattr(request.state, "request_id", None), "code": "INTERNAL_ERROR"},
    )
    return error_response(
        request, "INTERNAL_ERROR", "Unexpected error; use the request ID to contact support", 500
    )


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    from redis import Redis

    try:
        with engine.connect() as db:
            db.execute(text("SELECT 1"))
        Redis.from_url(cfg.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()
    except Exception as exc:
        raise AppError("NOT_READY", "Database or broker unavailable", 503) from exc
    return {"status": "ready"}
