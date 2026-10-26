from __future__ import annotations

from fastapi import APIRouter, Depends
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness — process is up. Never checks dependencies."""
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    """Readiness — dependencies (Postgres, Redis) are reachable."""
    checks = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:  # noqa: BLE001 - readiness check reports, doesn't hide
        checks["database"] = f"error: {e}"

    try:
        r = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["redis"] = f"error: {e}"

    healthy = all(v == "ok" for v in checks.values())
    return {"status": "ok" if healthy else "degraded", "checks": checks}
