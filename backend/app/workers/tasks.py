import asyncio
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Notification, Profile, Resume, User
from app.platforms.mock import MOCK_JOBS
from app.api.routes import analyze_job, ingest_job
from app.api.routes import discover_company_careers as run_company_career_discovery
from app.workers.celery_app import celery


@celery.task(name="job_agent.discover_mock")
def discover_mock(user_id: str) -> dict:
    db = SessionLocal()
    try:
        user = db.get(User, UUID(user_id))
        if not user:
            return {"status": "ignored", "reason": "user_not_found"}
        profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
        if not profile or not (profile.application_preferences or {}).get("automation_active"):
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


@celery.task(name="job_agent.discover_company_careers_for_user", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def discover_company_careers_for_user(user_id: str) -> dict:
    db = SessionLocal()
    try:
        user = db.get(User, UUID(user_id))
        if not user:
            return {"status": "ignored", "reason": "user_not_found"}
        profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
        if not profile or not (profile.application_preferences or {}).get("automation_active"):
            return {"status": "ignored", "reason": "automation_inactive"}
        result = asyncio.run(run_company_career_discovery(user=user, db=db))
        return {"status": "complete", "new": result["new"], "seen": result["count"]}
    finally:
        db.close()


@celery.task(name="job_agent.enqueue_active_company_career_discovery")
def enqueue_active_company_career_discovery() -> dict:
    db = SessionLocal()
    try:
        profiles = db.scalars(select(Profile)).all()
        user_ids = [str(profile.user_id) for profile in profiles if (profile.application_preferences or {}).get("automation_active")]
    finally:
        db.close()
    for user_id in user_ids:
        discover_company_careers_for_user.delay(user_id)
    return {"status": "queued", "users": len(user_ids)}
