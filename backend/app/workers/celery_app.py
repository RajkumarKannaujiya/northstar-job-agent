from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery = Celery("job_agent", broker=settings.redis_url, backend=settings.redis_url, include=["app.workers.tasks"])
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "discover-opted-in-company-career-boards-every-six-hours": {
            "task": "job_agent.enqueue_active_company_career_discovery",
            "schedule": crontab(minute=0, hour="*/6"),
        }
    },
)
