"""Celery app skeleton. One demo task (`ping`) to prove the broker wiring
end to end; real background jobs — scheduled discovery scans, automation
job execution — are Phase 3/7 work. Run with:
    celery -A app.worker worker --loglevel=info
"""
from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery("netsphere", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"])


@celery_app.task(name="netsphere.ping")
def ping() -> str:
    return "pong"


# Reserved for Phase 3: a periodic task that runs MockAWSProvider (or a real
# provider once configured) discovery for every active cloud_account on a
# schedule, via Celery beat. Not implemented — see ROADMAP.md.
