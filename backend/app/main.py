from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.config import settings
from app.logging_config import configure_logging, get_logger, request_id_ctx

configure_logging("DEBUG" if settings.debug else "INFO")
logger = get_logger("netsphere")

app = FastAPI(
    title=settings.app_name,
    description=settings.app_subtitle,
    version="0.1.0-phase1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = request_id_ctx.set(req_id)
    start = time.monotonic()
    try:
        response = await call_next(request)
    finally:
        request_id_ctx.reset(token)
    duration_ms = round((time.monotonic() - start) * 1000, 2)
    response.headers["X-Request-ID"] = req_id
    logger.info(
        "request handled",
        extra={"extra_fields": {
            "method": request.method, "path": request.url.path,
            "status_code": response.status_code, "duration_ms": duration_ms,
        }},
    )
    return response


app.include_router(api_router)
# /health, /ready, /metrics are also served un-versioned at the root, since
# that's where k8s-style probes and Prometheus scrape configs expect them.
app.include_router(health.router)
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/")
def root() -> dict:
    return {"name": settings.app_name, "subtitle": settings.app_subtitle, "docs": "/docs"}
