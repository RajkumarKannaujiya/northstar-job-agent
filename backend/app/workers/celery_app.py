from celery import Celery

from app.core.config import settings

celery = Celery("job_agent", broker=settings.redis_url, backend=settings.redis_url, include=["app.workers.tasks"])
celery.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"], timezone="UTC", enable_utc=True, task_acks_late=True, worker_prefetch_multiplier=1)
