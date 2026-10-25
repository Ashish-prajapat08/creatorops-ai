from celery import Celery

from app.core.config import settings
from app.core.observability import initialize

cfg = settings()
initialize()

celery = Celery("creatorops", broker=cfg.redis_url, include=["app.workers.tasks"])
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=240,
    task_time_limit=300,
    beat_schedule={
        "poll-email": {
            "task": "creatorops.poll_email",
            "schedule": cfg.email_sync_interval_seconds,
        },
        "scan-overdue": {"task": "creatorops.scan", "schedule": 300.0},
        "dispatch-outbox": {"task": "creatorops.dispatch", "schedule": 5.0},
    },
)
