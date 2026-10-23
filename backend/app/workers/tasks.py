from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Notification, Profile, Resume, User
from app.platforms.mock import MOCK_JOBS
from app.api.routes import analyze_job, ingest_job
from app.workers.celery_app import celery


@celery.task(name="job_agent.discover_mock")
def discover_mock(user_id: str) -> dict:
    db = SessionLocal()
    try:
        user = db.get(User, UUID(user_id))
        if not user:
            return {"status": "ignored", "reason": "user_not_found"}
        profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
        if not profile or not profile.application_preferences.get("automation_active"):
            return {"status": "ignored", "reason": "automation_inactive"}
        count = 0
        for item in MOCK_JOBS:
            job = ingest_job(item, user, db)
            if db.scalar(select(Resume.id).where(Resume.user_id == user.id)):
                analyze_job(job, user, db)
            count += 1
        db.add(Notification(user_id=user.id, kind="JOB_FOUND", title="Mock discovery complete", body=f"Found {count} synthetic demo jobs."))
        db.commit()
        return {"status": "complete", "discovered": count}
    finally:
        db.close()


@celery.task(name="job_agent.health_check")
def health_check() -> dict:
    return {"status": "ok", "connectors": "manual_only"}
