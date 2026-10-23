import logging
import re
import io
import zipfile
import asyncio
import hmac
from difflib import SequenceMatcher
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.metrics import increment, observe_match_score
from app.core.security import create_access_token, hash_password, verify_password
from app.core.storage import delete_encrypted, read_encrypted, save_encrypted
from app.models import (Application, ApplicationAnswer, ApplicationEvent, ApplicationQuestion, ApplicationStatus,
                        AutomationTask,
                        AuditLog, Job, JobMatch, JobSkill, JobSource, JobSourceMapping, Notification,
                        PlatformAccount, Profile, Resume, ResumeSkill, ResumeVersion, Skill, User)
from app.platforms.mock import MOCK_JOBS
from app.platforms.career_pages import fetch_board, validate_board
from app.services.decisions import decide_application
from app.services.matching import canonical_job_key, normalize_text, score_job
from app.services.questions import answer_from_verified_sources, classify_question
from app.services.resume_parser import extract_text, parse_resume
from app.services.transitions import transition

logger = logging.getLogger(__name__)
router = APIRouter()


class RegisterInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginInput(BaseModel):
    email: EmailStr
    password: str


class ProfileInput(BaseModel):
    personal: dict[str, Any] = Field(default_factory=dict)
    professional: dict[str, Any] = Field(default_factory=dict)
    education: dict[str, Any] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    application_preferences: dict[str, Any] = Field(default_factory=dict)
    answer_bank: list[dict[str, Any]] = Field(default_factory=list)


class JobInput(BaseModel):
    platform: str = "manual"
    platform_job_id: str
    title: str
    company: str
    location: str = ""
    remote_type: str = "UNKNOWN"
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str | None = None
    experience_min: float | None = None
    experience_max: float | None = None
    skills: list[str] = Field(default_factory=list)
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    employment_type: str = "UNKNOWN"
    posted_at: datetime | None = None
    application_url: str
    application_type: str = "EXTERNAL"
    recruiter: str | None = None
    source_url: str = ""

    @field_validator("application_url", "source_url")
    @classmethod
    def require_safe_url(cls, value: str) -> str:
        if value and not value.lower().startswith("https://"):
            raise ValueError("Job links must use HTTPS")
        return value


class ConfirmationInput(BaseModel):
    confirmation_signal: str = Field(min_length=3, max_length=80)
    confirmation_reference: str = Field(min_length=3, max_length=300)
    confirmation_text: str | None = None


class ResumeOverrideInput(BaseModel):
    resume_id: UUID


class TransitionInput(BaseModel):
    target_status: ApplicationStatus
    detail: dict[str, Any] = Field(default_factory=dict)


class FailureInput(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class NotificationReadInput(BaseModel):
    read: bool = True


class CareerBoardInput(BaseModel):
    provider: Literal["greenhouse", "lever"]
    board_token: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    company_name: str = Field(min_length=1, max_length=200)

    @field_validator("board_token", mode="before")
    @classmethod
    def strip_board_token(cls, value: str) -> str:
        return str(value).strip()


class CareerBoardsInput(BaseModel):
    boards: list[CareerBoardInput] = Field(default_factory=list, max_length=10)

    @field_validator("boards")
    @classmethod
    def no_duplicate_boards(cls, boards: list[CareerBoardInput]) -> list[CareerBoardInput]:
        keys = [(board.provider, board.board_token.casefold()) for board in boards]
        if len(keys) != len(set(keys)):
            raise ValueError("A career board can be added only once")
        return boards


def _profile_dict(profile: Profile | None) -> dict:
    if not profile:
        return {}
    return {key: getattr(profile, key) or {} for key in ("personal", "professional", "education", "preferences", "application_preferences")} | {"answer_bank": profile.answer_bank or []}


def _job_dict(job: Job, db: Session | None = None) -> dict:
    result = {key: getattr(job, key) for key in ("id", "title", "company", "location", "remote_type", "salary_min", "salary_max", "currency", "experience_min", "experience_max", "skills", "description", "requirements", "benefits", "employment_type", "posted_at", "application_url", "application_type", "recruiter", "created_at")}
    result["id"] = str(job.id)
    if db:
        sources = db.scalars(select(JobSourceMapping).where(JobSourceMapping.job_id == job.id)).all()
        result["sources"] = [{"platform": s.platform, "platform_job_id": s.platform_job_id, "source_url": s.source_url} for s in sources]
    return result


def _audit(db: Session, user_id: UUID, action: str, entity_type: str, entity_id: str | None = None, detail: dict | None = None) -> None:
    db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id, detail=detail or {}))


def _ensure_skill(db: Session, name: str, category: str = "technical") -> Skill:
    canonical_name = name.strip().casefold()
    skill = db.scalar(select(Skill).where(Skill.canonical_name == canonical_name))
    if not skill:
        skill = Skill(canonical_name=canonical_name, category=category)
        db.add(skill)
        db.flush()
    return skill


def _validate_resume_bytes(suffix: str, content: bytes) -> None:
    if suffix == "pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(415, "The file contents do not look like a PDF")
    if suffix == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                total_size = sum(entry.file_size for entry in entries)
                if "word/document.xml" not in archive.namelist() or len(entries) > 2000 or total_size > settings.max_resume_bytes * 5:
                    raise HTTPException(415, "The DOCX file is invalid or exceeds expanded-size limits")
        except zipfile.BadZipFile as exc:
            raise HTTPException(415, "The file contents do not look like a DOCX document") from exc
    if suffix == "txt" and b"\x00" in content:
        raise HTTPException(415, "Text resumes cannot contain binary data")


@router.post("/auth/register", status_code=201)
def register(payload: RegisterInput, db: Session = Depends(get_db)):
    if not re.search(r"[A-Za-z]", payload.password) or not re.search(r"\d", payload.password):
        raise HTTPException(422, "Password must contain letters and numbers")
    user = User(email=payload.email.lower(), password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.flush()
        db.add(Profile(user_id=user.id, application_preferences={"mode": "ASSISTED", "auto_apply_enabled": False, "auto_apply_threshold": 85, "review_threshold": 70, "max_daily_applications": 10, "max_applications_per_company": 2, "job_age_limit_hours": 24}))
        _audit(db, user.id, "ACCOUNT_REGISTERED", "user", str(user.id))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists") from exc
    return {"access_token": create_access_token(str(user.id)), "token_type": "bearer", "user": {"id": str(user.id), "email": user.email}}


@router.post("/auth/login")
def login(payload: LoginInput, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": create_access_token(str(user.id)), "token_type": "bearer", "user": {"id": str(user.id), "email": user.email}}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": str(user.id), "email": user.email, "created_at": user.created_at}


@router.get("/me/export")
def export_account_data(user: User = Depends(current_user), db: Session = Depends(get_db)):
    resumes = db.scalars(select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at)).all()
    applications = db.scalars(select(Application).where(Application.user_id == user.id).order_by(Application.created_at)).all()
    application_ids = [item.id for item in applications]
    events = db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id.in_(application_ids))).all() if application_ids else []
    questions = db.scalars(select(ApplicationQuestion).where(ApplicationQuestion.application_id.in_(application_ids))).all() if application_ids else []
    notification_rows = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at)).all()
    return {
        "exported_at": datetime.now(timezone.utc),
        "account": {"id": str(user.id), "email": user.email, "created_at": user.created_at},
        "profile": _profile_dict(db.scalar(select(Profile).where(Profile.user_id == user.id))),
        "resumes": [_resume_out(item) for item in resumes],
        "applications": [
            {
                **_application_out(item, db.get(Job, item.job_id)),
                "events": [
                    {"type": event.event_type, "detail": event.detail, "occurred_at": event.occurred_at}
                    for event in events if event.application_id == item.id
                ],
                "questions": [
                    {"question": question.question, "classification": question.classification,
                     "answer": question.answer, "confidence": question.confidence,
                     "answer_source": question.answer_source, "requires_user_input": question.requires_user_input}
                    for question in questions if question.application_id == item.id
                ],
            }
            for item in applications
        ],
        "notifications": [
            {"kind": item.kind, "title": item.title, "body": item.body, "link": item.link,
             "read": item.read, "created_at": item.created_at}
            for item in notification_rows
        ],
    }


@router.delete("/me", status_code=204)
def delete_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    resume_rows = db.scalars(select(Resume).where(Resume.user_id == user.id)).all()
    resume_ids = [item.id for item in resume_rows]
    application_ids = select(Application.id).where(Application.user_id == user.id)
    if resume_ids:
        db.execute(delete(ResumeVersion).where(ResumeVersion.resume_id.in_(resume_ids)))
        db.execute(delete(ResumeSkill).where(ResumeSkill.resume_id.in_(resume_ids)))
    db.execute(delete(ApplicationQuestion).where(ApplicationQuestion.application_id.in_(application_ids)))
    db.execute(delete(ApplicationEvent).where(ApplicationEvent.application_id.in_(application_ids)))
    db.execute(delete(Application).where(Application.user_id == user.id))
    for model in (ApplicationAnswer, JobMatch, JobSource, PlatformAccount, AutomationTask, Notification, AuditLog):
        db.execute(delete(model).where(model.user_id == user.id))
    db.execute(delete(Resume).where(Resume.user_id == user.id))
    db.execute(delete(Profile).where(Profile.user_id == user.id))
    db.delete(user)
    db.commit()
    cleanup_failed = []
    for resume in resume_rows:
        try:
            delete_encrypted(resume.storage_key)
        except Exception:
            logger.exception("resume_storage_cleanup_failed")
            cleanup_failed.append(resume.storage_key)
    if cleanup_failed:
        logger.error("encrypted_resume_cleanup_pending count=%d", len(cleanup_failed))
    return Response(status_code=204)


@router.get("/profile")
def get_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _profile_dict(db.scalar(select(Profile).where(Profile.user_id == user.id)))


@router.put("/profile")
def put_profile(payload: ProfileInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if not profile:
        profile = Profile(user_id=user.id)
        db.add(profile)
    for key in ("personal", "professional", "education", "preferences", "application_preferences", "answer_bank"):
        setattr(profile, key, getattr(payload, key))
    _audit(db, user.id, "PROFILE_UPDATED", "profile", str(profile.id))
    db.commit()
    return _profile_dict(profile)


@router.post("/resumes/upload", status_code=201)
async def upload_resume(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    filename = (file.filename or "resume").replace("\\", "/").split("/")[-1]
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"pdf", "docx", "txt"}:
        raise HTTPException(415, "Upload a PDF, DOCX, or TXT file")
    content = await file.read(settings.max_resume_bytes + 1)
    if not content or len(content) > settings.max_resume_bytes:
        raise HTTPException(413, "Resume is empty or exceeds the configured size limit")
    _validate_resume_bytes(suffix, content)
    try:
        extracted = extract_text(filename, content)
    except Exception as exc:
        logger.exception("resume_extraction_failed filename=%s", filename)
        raise HTTPException(422, "Resume extraction failed. Check the file format and try again.") from exc
    parsed = parse_resume(extracted)
    key = save_encrypted(content, "." + suffix)
    resume = Resume(user_id=user.id, filename=filename, content_type=file.content_type or "application/octet-stream", storage_key=key, parsed_data=parsed, extracted_text=extracted)
    db.add(resume)
    try:
        existing_resumes = db.scalar(select(Resume.id).where(Resume.user_id == user.id).limit(1))
        if not existing_resumes:
            resume.is_preferred = True
        profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
        if not profile:
            profile = Profile(user_id=user.id)
            db.add(profile)
        personal = dict(profile.personal or {})
        for field in ("full_name", "email", "phone", "location"):
            parsed_field = "name" if field == "full_name" else field
            if parsed.get(parsed_field) and not personal.get(field):
                personal[field] = parsed[parsed_field]
        professional = dict(profile.professional or {})
        if parsed.get("explicit_skills") and not professional.get("skills"):
            professional["skills"] = parsed["explicit_skills"]
        if parsed.get("job_titles") and not professional.get("resume_job_titles"):
            professional["resume_job_titles"] = parsed["job_titles"]
        if parsed.get("years_of_experience") and not professional.get("total_experience"):
            professional["total_experience"] = parsed["years_of_experience"]
        education = dict(profile.education or {})
        if parsed.get("degree") and not education.get("degree"):
            education["degree"] = parsed["degree"]
        if parsed.get("graduation_year") and not education.get("graduation_year"):
            education["graduation_year"] = parsed["graduation_year"]
        profile.personal = personal
        profile.professional = professional
        profile.education = education
        db.flush()
        db.add(ResumeVersion(resume_id=resume.id, version=1, filename=filename, storage_key=key, parsed_data=parsed))
        for name in parsed.get("explicit_skills", []):
            skill = _ensure_skill(db, name, "soft" if name in parsed.get("soft_skills", []) else "technical")
            db.add(ResumeSkill(resume_id=resume.id, skill_id=skill.id, evidence_type="EXPLICIT", confidence=1.0, evidence=name))
        _audit(db, user.id, "RESUME_UPLOADED", "resume", detail={"filename": filename, "bytes": len(content)})
        db.commit()
    except Exception:
        db.rollback()
        delete_encrypted(key)
        raise
    return _resume_out(resume)


def _resume_out(resume: Resume) -> dict:
    return {"id": str(resume.id), "filename": resume.filename, "content_type": resume.content_type, "parsed_data": resume.parsed_data, "is_preferred": resume.is_preferred, "created_at": resume.created_at}


@router.get("/resumes")
def list_resumes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_resume_out(x) for x in db.scalars(select(Resume).where(Resume.user_id == user.id).order_by(desc(Resume.created_at))).all()]


@router.get("/resumes/{resume_id}/download")
def download_resume(resume_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    resume = db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id))
    if not resume:
        raise HTTPException(404, "Resume not found")
    try:
        content = read_encrypted(resume.storage_key)
    except Exception as exc:
        logger.exception("resume_download_failed resume_id=%s", resume_id)
        raise HTTPException(503, "Resume storage is temporarily unavailable") from exc
    suffix = resume.filename.rsplit(".", 1)[-1].lower()
    media_type = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "txt": "text/plain"}.get(suffix, "application/octet-stream")
    filename = quote(resume.filename.replace("\r", "").replace("\n", ""), safe="")
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}", "Cache-Control": "no-store"})


@router.put("/resumes/{resume_id}/preferred")
def set_preferred_resume(resume_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    resumes = db.scalars(select(Resume).where(Resume.user_id == user.id)).all()
    target = next((item for item in resumes if item.id == resume_id), None)
    if not target:
        raise HTTPException(404, "Resume not found")
    for item in resumes:
        item.is_preferred = item.id == resume_id
    _audit(db, user.id, "PREFERRED_RESUME_CHANGED", "resume", str(resume_id))
    db.commit()
    return _resume_out(target)


@router.delete("/resumes/{resume_id}", status_code=204)
def remove_resume(resume_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    resume = db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id))
    if not resume: raise HTTPException(404, "Resume not found")
    storage_key = resume.storage_key
    db.delete(resume)
    _audit(db, user.id, "RESUME_DELETED", "resume", str(resume_id))
    db.commit()
    delete_encrypted(storage_key)


def ingest_job(payload: dict, user: User, db: Session) -> Job:
    platform = payload.get("platform", "manual").lower()
    external_id = str(payload["platform_job_id"])
    existing_mapping = db.scalar(select(JobSourceMapping).where(JobSourceMapping.platform == platform, JobSourceMapping.platform_job_id == external_id))
    if existing_mapping:
        return db.get(Job, existing_mapping.job_id)
    key = canonical_job_key(payload)
    job = db.scalar(select(Job).where(Job.canonical_key == key))
    if not job:
        company_norm = normalize_text(payload.get("company", ""))
        title_norm = normalize_text(payload.get("title", ""))
        location_norm = normalize_text(payload.get("location", ""))
        description_norm = normalize_text(payload.get("description", ""))
        candidates = db.scalars(select(Job).where(Job.company.ilike(f"%{payload.get('company', '')}%")).limit(50)).all()
        for candidate in candidates:
            company_ratio = SequenceMatcher(None, company_norm, normalize_text(candidate.company)).ratio()
            title_ratio = SequenceMatcher(None, title_norm, normalize_text(candidate.title)).ratio()
            location_ratio = SequenceMatcher(None, location_norm, normalize_text(candidate.location)).ratio()
            description_ratio = SequenceMatcher(None, description_norm, normalize_text(candidate.description)).ratio()
            if company_ratio >= 0.9 and title_ratio >= 0.88 and (location_ratio >= 0.75 or description_ratio >= 0.92):
                job = candidate
                break
    if not job:
        data = {key: payload.get(key) for key in ("title", "company", "location", "remote_type", "salary_min", "salary_max", "currency", "experience_min", "experience_max", "skills", "description", "requirements", "benefits", "employment_type", "posted_at", "application_url", "application_type", "recruiter")}
        job = Job(canonical_key=key, **data)
        db.add(job)
        db.flush()
    db.add(JobSourceMapping(job_id=job.id, platform=platform, platform_job_id=external_id, source_url=payload.get("source_url") or payload["application_url"]))
    for name in payload.get("skills", []):
        skill = _ensure_skill(db, name)
        if not db.scalar(select(JobSkill.id).where(JobSkill.job_id == job.id, JobSkill.skill_id == skill.id)):
            db.add(JobSkill(job_id=job.id, skill_id=skill.id, requirement_type="REQUIRED"))
    return job


@router.post("/jobs", status_code=201)
def add_job(payload: JobInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = ingest_job(payload.model_dump(), user, db)
    db.commit()
    db.refresh(job)
    return _job_dict(job, db)


@router.get("/jobs")
def list_jobs(q: str | None = None, min_score: float | None = None, limit: int = 100, user: User = Depends(current_user), db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    query = select(Job).order_by(desc(Job.posted_at), desc(Job.created_at)).limit(limit)
    if q: query = query.where(Job.title.ilike(f"%{q}%") | Job.company.ilike(f"%{q}%") | Job.location.ilike(f"%{q}%"))
    jobs = db.scalars(query).all()
    result = []
    for job in jobs:
        data = _job_dict(job, db)
        match = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == job.id))
        data["match"] = {"score": match.match_score, "breakdown": match.breakdown, "reasons": match.reasons, "missing": match.missing, "resume_id": str(match.resume_id) if match.resume_id else None} if match else None
        if min_score is None or (match and match.match_score >= min_score): result.append(data)
    return result


@router.get("/jobs/{job_id}")
def get_job(job_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    return _job_dict(job, db)


def analyze_job(job: Job, user: User, db: Session) -> dict:
    resumes = db.scalars(select(Resume).where(Resume.user_id == user.id)).all()
    if not resumes: raise HTTPException(400, "Upload a resume before analyzing jobs")
    profile = _profile_dict(db.scalar(select(Profile).where(Profile.user_id == user.id)))
    match = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == job.id))
    override_resume = db.get(Resume, match.resume_id) if match and match.manual_resume_override and match.resume_id else None
    if override_resume and override_resume.user_id == user.id:
        result, best_resume = score_job(_job_dict(job), override_resume.parsed_data, profile), override_resume
    else:
        scored = [(score_job(_job_dict(job), resume.parsed_data, profile), resume) for resume in resumes]
        result, best_resume = max(scored, key=lambda pair: pair[0]["match_score"])
    if not match:
        match = JobMatch(user_id=user.id, job_id=job.id)
        db.add(match)
    match.resume_id = best_resume.id
    match.match_score = result["match_score"]
    match.breakdown = result["breakdown"]
    match.reasons = result["reasons"]
    match.missing = result["missing"]
    db.flush()
    increment("jobs_matched_total")
    observe_match_score(match.match_score)
    decision = decide_application(_job_dict(job), match.match_score, profile, connector_supports_application=False)
    return {**result, "resume_id": str(best_resume.id), "resume_filename": best_resume.filename, "decision": decision}


@router.post("/jobs/{job_id}/resume")
def override_resume(job_id: UUID, payload: ResumeOverrideInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    resume = db.scalar(select(Resume).where(Resume.id == payload.resume_id, Resume.user_id == user.id))
    if not job: raise HTTPException(404, "Job not found")
    if not resume: raise HTTPException(404, "Resume not found")
    profile = _profile_dict(db.scalar(select(Profile).where(Profile.user_id == user.id)))
    result = score_job(_job_dict(job), resume.parsed_data, profile)
    match = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == job.id))
    if not match:
        match = JobMatch(user_id=user.id, job_id=job.id)
        db.add(match)
    match.resume_id = resume.id
    match.manual_resume_override = True
    match.match_score = result["match_score"]
    match.breakdown = result["breakdown"]
    match.reasons = result["reasons"]
    match.missing = result["missing"]
    _audit(db, user.id, "JOB_RESUME_OVERRIDE", "job", str(job.id), {"resume_id": str(resume.id)})
    db.commit()
    return {**result, "resume_id": str(resume.id), "resume_filename": resume.filename, "manual_override": True}


@router.post("/jobs/{job_id}/analyze")
def analyze(job_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    result = analyze_job(job, user, db)
    _audit(db, user.id, "JOB_ANALYZED", "job", str(job_id), {"score": result["match_score"]})
    db.commit()
    return result


@router.post("/jobs/discover-mock")
def discover_mock(user: User = Depends(current_user), db: Session = Depends(get_db)):
    discovered = []
    for payload in MOCK_JOBS:
        job = ingest_job(payload, user, db)
        db.flush()
        result = analyze_job(job, user, db) if db.scalar(select(Resume.id).where(Resume.user_id == user.id)) else None
        discovered.append({"job": _job_dict(job, db), "analysis": result})
    increment("jobs_discovered_total", len(discovered))
    db.add(Notification(user_id=user.id, kind="JOB_FOUND", title="Mock discovery complete", body=f"Processed {len(discovered)} sample jobs."))
    _audit(db, user.id, "MOCK_DISCOVERY_RUN", "job", detail={"count": len(discovered)})
    db.commit()
    return {"count": len(discovered), "items": discovered}


@router.post("/applications", status_code=201)
def create_application(job_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    existing = db.scalar(select(Application).where(Application.user_id == user.id, Application.job_id == job.id))
    if existing: raise HTTPException(409, "An application record already exists for this job")
    match = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == job.id))
    if not match:
        analysis = analyze_job(job, user, db)
        match = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == job.id))
    profile = _profile_dict(db.scalar(select(Profile).where(Profile.user_id == user.id)))
    policy = profile.get("application_preferences", {})
    now = datetime.now(timezone.utc)
    existing_apps = db.scalars(select(Application).where(Application.user_id == user.id)).all()
    today_count = sum(1 for item in existing_apps if item.created_at and item.created_at.date() == now.date())
    hour_count = sum(1 for item in existing_apps if item.created_at and (now - (item.created_at.replace(tzinfo=timezone.utc) if item.created_at.tzinfo is None else item.created_at.astimezone(timezone.utc))).total_seconds() < 3600)
    company_count = sum(1 for item in existing_apps if item.created_at and item.created_at.date() == now.date() and db.get(Job, item.job_id).company.casefold() == job.company.casefold())
    if today_count >= int(policy.get("max_daily_applications", 10)):
        raise HTTPException(429, "Daily application tracking limit reached")
    if hour_count >= int(policy.get("max_hourly_applications", 5)):
        raise HTTPException(429, "Hourly application tracking limit reached")
    if company_count >= int(policy.get("max_applications_per_company", 2)):
        raise HTTPException(429, "Company application limit reached")
    decision = decide_application(_job_dict(job), match.match_score if match else 0, profile, connector_supports_application=False)
    state = ApplicationStatus.MANUAL_ACTION_REQUIRED if decision["decision"] != "SKIP" else ApplicationStatus.SKIPPED
    app = Application(user_id=user.id, job_id=job.id, platform=(db.scalar(select(JobSourceMapping.platform).where(JobSourceMapping.job_id == job.id)) or "manual"), resume_id=match.resume_id if match else None, match_score=match.match_score if match else 0, status=state, application_url=job.application_url, failure_reason="No permitted application connector is configured" if state == ApplicationStatus.MANUAL_ACTION_REQUIRED else "Below configured review threshold")
    db.add(app)
    db.flush()
    db.add(ApplicationEvent(application_id=app.id, event_type=state.value, detail={"decision": decision}))
    increment("applications_started_total")
    if state == ApplicationStatus.MANUAL_ACTION_REQUIRED:
        increment("manual_actions_total")
    db.add(Notification(user_id=user.id, kind=state.value, title="Manual application action required" if state == ApplicationStatus.MANUAL_ACTION_REQUIRED else "Job skipped", body=f"{job.title} at {job.company}", link=job.application_url))
    _audit(db, user.id, "APPLICATION_CREATED", "application", str(app.id), {"status": state.value})
    db.commit()
    return _application_out(app, job)


def _application_out(application: Application, job: Job) -> dict:
    return {"id": str(application.id), "job_id": str(job.id), "job_title": job.title, "company": job.company, "platform": application.platform, "resume_id": str(application.resume_id) if application.resume_id else None, "match_score": application.match_score, "status": application.status.value, "application_url": application.application_url, "failure_reason": application.failure_reason, "created_at": application.created_at}


@router.get("/applications")
def list_applications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    apps = db.scalars(select(Application).where(Application.user_id == user.id).order_by(desc(Application.created_at))).all()
    return [_application_out(app, db.get(Job, app.job_id)) for app in apps]


@router.get("/applications/{application_id}")
def get_application(application_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user.id))
    if not app: raise HTTPException(404, "Application not found")
    job = db.get(Job, app.job_id)
    events = db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == app.id).order_by(ApplicationEvent.occurred_at)).all()
    questions = db.scalars(select(ApplicationQuestion).where(ApplicationQuestion.application_id == app.id)).all()
    return {**_application_out(app, job), "events": [{"type": e.event_type, "detail": e.detail, "occurred_at": e.occurred_at} for e in events], "questions": [{"question": q.question, "classification": q.classification, "answer": q.answer, "confidence": q.confidence, "answer_source": q.answer_source, "requires_user_input": q.requires_user_input} for q in questions]}


@router.post("/applications/{application_id}/transition")
def transition_application(application_id: UUID, payload: TransitionInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user.id))
    if not app: raise HTTPException(404, "Application not found")
    try:
        transition(app.status, payload.target_status)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    app.status = payload.target_status
    if payload.target_status == ApplicationStatus.APPLICATION_STARTED and app.started_at is None:
        app.started_at = datetime.now(timezone.utc)
    db.add(ApplicationEvent(application_id=app.id, event_type=payload.target_status.value, detail=payload.detail))
    if payload.target_status == ApplicationStatus.MANUAL_ACTION_REQUIRED:
        increment("manual_actions_total")
        db.add(Notification(user_id=user.id, kind="MANUAL_ACTION_REQUIRED", title="Your action is needed", body=payload.detail.get("reason", "Continue this application manually."), link=app.application_url))
    _audit(db, user.id, "APPLICATION_STATE_CHANGED", "application", str(app.id), {"status": payload.target_status.value})
    db.commit()
    return _application_out(app, db.get(Job, app.job_id))


@router.post("/applications/{application_id}/failure")
def fail_application(application_id: UUID, payload: FailureInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user.id))
    if not app: raise HTTPException(404, "Application not found")
    try:
        transition(app.status, ApplicationStatus.FAILED)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    app.status = ApplicationStatus.FAILED
    app.failure_reason = payload.reason
    increment("applications_failed_total")
    db.add(ApplicationEvent(application_id=app.id, event_type="APPLICATION_FAILED", detail={"reason": payload.reason}))
    db.add(Notification(user_id=user.id, kind="APPLICATION_FAILED", title="Application failed", body=payload.reason, link=app.application_url))
    _audit(db, user.id, "APPLICATION_FAILED", "application", str(app.id), {"reason": payload.reason})
    db.commit()
    return _application_out(app, db.get(Job, app.job_id))


@router.post("/applications/{application_id}/questions")
def add_question(application_id: UUID, question: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user.id))
    if not app: raise HTTPException(404, "Application not found")
    profile = _profile_dict(db.scalar(select(Profile).where(Profile.user_id == user.id)))
    resume = db.get(Resume, app.resume_id) if app.resume_id else None
    result = answer_from_verified_sources(question, profile, resume.parsed_data if resume else {}, profile.get("answer_bank", []))
    q = ApplicationQuestion(application_id=app.id, question=question, classification=classify_question(question), answer=result["answer"], confidence=result["confidence"], answer_source=result["source"], requires_user_input=result["requires_user_input"])
    db.add(q)
    if result["requires_user_input"]:
        app.status = ApplicationStatus.MANUAL_ACTION_REQUIRED
        db.add(ApplicationEvent(application_id=app.id, event_type="QUESTION_DETECTED", detail={"classification": q.classification, "reason": "No verified answer found"}))
    db.commit()
    return {"question": question, "classification": q.classification, **result}


@router.post("/applications/{application_id}/confirm-submission")
def confirm_submission(application_id: UUID, payload: ConfirmationInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user.id))
    if not app: raise HTTPException(404, "Application not found")
    accepted = {"confirmation_page", "confirmation_message", "application_id", "platform_response", "user_verified_receipt"}
    if payload.confirmation_signal not in accepted:
        raise HTTPException(422, "Submission confirmation requires a supported confirmation signal")
    try:
        transition(app.status, ApplicationStatus.SUBMITTED, confirmed_submission=True)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    app.status = ApplicationStatus.SUBMITTED
    increment("applications_submitted_total")
    app.submitted_at = datetime.now(timezone.utc)
    app.confirmation_reference = payload.confirmation_reference
    app.confirmation_text = payload.confirmation_text
    db.add(ApplicationEvent(application_id=app.id, event_type="APPLICATION_SUBMITTED", detail={"confirmation_signal": payload.confirmation_signal, "reference": payload.confirmation_reference}))
    db.add(Notification(user_id=user.id, kind="APPLICATION_SUBMITTED", title="Application submission recorded", body=f"Confirmation recorded for application {app.id}"))
    _audit(db, user.id, "APPLICATION_SUBMISSION_CONFIRMED", "application", str(app.id), {"signal": payload.confirmation_signal})
    db.commit()
    return _application_out(app, db.get(Job, app.job_id))


@router.get("/platforms")
def list_platforms(user: User = Depends(current_user), db: Session = Depends(get_db)):
    names = ["naukri", "indeed", "linkedin", "apna", "foundit", "internshala", "wellfound", "cutshort", "shine", "timesjobs", "glassdoor", "company_careers", "greenhouse", "lever"]
    records = {x.platform: x for x in db.scalars(select(JobSource).where(JobSource.user_id == user.id)).all()}
    return [{
        "platform": name,
        "status": records[name].status if name in records else "DISCONNECTED",
        "automation_available": bool(records[name].automation_available) if name in records else False,
        "supported_mode": "public job discovery; application stays on employer site" if name in {"greenhouse", "lever"} else "manual link-out; no official integration configured",
    } for name in names]


@router.get("/platforms/company-careers")
def list_company_career_boards(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    return {"boards": (profile.preferences or {}).get("company_career_boards", []) if profile else []}


@router.put("/platforms/company-careers")
def save_company_career_boards(payload: CareerBoardsInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if not profile:
        profile = Profile(user_id=user.id)
        db.add(profile)
    preferences = dict(profile.preferences or {})
    preferences["company_career_boards"] = [board.model_dump() for board in payload.boards]
    profile.preferences = preferences
    configured = {(board.provider, board.board_token) for board in payload.boards}
    for provider in ("greenhouse", "lever"):
        source = db.scalar(select(JobSource).where(JobSource.user_id == user.id, JobSource.platform == provider))
        provider_configured = any(item[0] == provider for item in configured)
        if provider_configured and not source:
            db.add(JobSource(user_id=user.id, platform=provider, status="CONNECTED_READ_ONLY", automation_available=True))
        elif source and not provider_configured:
            source.status = "DISCONNECTED"
            source.automation_available = False
    _audit(db, user.id, "COMPANY_CAREER_BOARDS_UPDATED", "profile", str(profile.id), {"count": len(payload.boards)})
    db.commit()
    return {"boards": preferences["company_career_boards"], "message": "Only published jobs are read; application submission remains manual."}


@router.post("/jobs/discover-company-careers")
async def discover_company_careers(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    boards = (profile.preferences or {}).get("company_career_boards", []) if profile else []
    if not boards:
        raise HTTPException(409, "Add a Greenhouse or Lever company board before discovery")

    semaphore = asyncio.Semaphore(3)

    async def load_board(board: dict[str, Any]):
        async with semaphore:
            return await fetch_board(board["provider"], board["board_token"], board.get("company_name", board["board_token"]))

    fetched = await asyncio.gather(*(load_board(board) for board in boards), return_exceptions=True)
    resume_exists = db.scalar(select(Resume.id).where(Resume.user_id == user.id)) is not None
    total_new = 0
    total_seen = 0
    report = []
    for board, result in zip(boards, fetched):
        provider = board["provider"]
        source = db.scalar(select(JobSource).where(JobSource.user_id == user.id, JobSource.platform == provider))
        if not source:
            source = JobSource(user_id=user.id, platform=provider, status="CONNECTED_READ_ONLY", automation_available=True)
            db.add(source)
        if isinstance(result, Exception):
            source.error_count = (source.error_count or 0) + 1
            source.last_error = "Public career board request failed"
            source.status = "DEGRADED" if source.error_count >= 3 else "CONNECTED_READ_ONLY"
            report.append({"provider": provider, "board_token": board["board_token"], "status": "failed", "count": 0})
            increment("connector_errors_total")
            continue

        source.status = "CONNECTED_READ_ONLY"
        source.automation_available = True
        source.error_count = 0
        source.last_error = None
        source.last_success_at = datetime.now(timezone.utc)
        board_new = 0
        for item in result:
            mapped_id = item["platform_job_id"]
            existing = db.scalar(select(JobSourceMapping.id).where(JobSourceMapping.platform == provider, JobSourceMapping.platform_job_id == mapped_id))
            job = ingest_job(item, user, db)
            db.flush()
            if existing is None:
                board_new += 1
            if resume_exists:
                analyze_job(job, user, db)
        total_new += board_new
        total_seen += len(result)
        report.append({"provider": provider, "board_token": board["board_token"], "status": "ok", "count": len(result), "new": board_new})

    if total_new:
        db.add(Notification(user_id=user.id, kind="JOB_FOUND", title="New company career jobs found", body=f"Found {total_new} new published jobs across your saved boards."))
    increment("jobs_discovered_total", total_new)
    _audit(db, user.id, "COMPANY_CAREER_DISCOVERY_RUN", "job", detail={"new": total_new, "seen": total_seen})
    db.commit()
    return {"count": total_seen, "new": total_new, "boards": report, "mode": "read_only_public_jobs"}


@router.post("/internal/scheduled-discovery", include_in_schema=False)
async def run_scheduled_discovery(x_scheduler_secret: str | None = Header(default=None), db: Session = Depends(get_db)):
    expected = settings.scheduler_shared_secret
    if not expected or not x_scheduler_secret or not hmac.compare_digest(expected, x_scheduler_secret):
        raise HTTPException(404, "Not found")
    profiles = db.scalars(select(Profile).order_by(Profile.updated_at.asc())).all()
    active = [profile for profile in profiles if (profile.application_preferences or {}).get("automation_active") and (profile.preferences or {}).get("company_career_boards")]
    report = []
    for profile in active[:20]:
        user = db.get(User, profile.user_id)
        if not user:
            continue
        profile.updated_at = datetime.now(timezone.utc)
        try:
            result = await discover_company_careers(user=user, db=db)
            report.append({"status": "ok", "new": result["new"], "seen": result["count"]})
        except Exception:
            db.rollback()
            logger.exception("scheduled_company_discovery_failed user_id=%s", user.id)
            report.append({"status": "failed"})
    return {"processed": len(report), "users": report}


@router.post("/platforms/connect")
def connect_platform(platform: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    platform = platform.lower().strip()
    allowed = {"naukri", "indeed", "linkedin", "apna", "foundit", "internshala", "wellfound", "cutshort", "shine", "timesjobs", "glassdoor", "company_careers"}
    if platform not in allowed: raise HTTPException(422, "Unknown platform")
    source = db.scalar(select(JobSource).where(JobSource.user_id == user.id, JobSource.platform == platform))
    if not source:
        source = JobSource(user_id=user.id, platform=platform, status="MANUAL_ONLY", automation_available=False)
        db.add(source)
    db.commit()
    return {"platform": platform, "status": source.status, "automation_available": False, "message": "No official credential or permitted submission connector is configured. Jobs can be saved and opened manually."}


@router.delete("/platforms/{platform}", status_code=204)
def disconnect_platform(platform: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    source = db.scalar(select(JobSource).where(JobSource.user_id == user.id, JobSource.platform == platform.lower()))
    if source: db.delete(source); db.commit()


@router.get("/automation/status")
def automation_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = _profile_dict(db.scalar(select(Profile).where(Profile.user_id == user.id)))
    prefs = profile.get("application_preferences", {})
    return {"active": bool(prefs.get("automation_active", False)), "mode": prefs.get("mode", "ASSISTED"), "auto_apply_enabled": bool(prefs.get("auto_apply_enabled", False)), "limits": prefs}


def set_automation(active: bool, user: User, db: Session):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if not profile:
        profile = Profile(user_id=user.id, application_preferences={})
        db.add(profile)
    prefs = dict(profile.application_preferences or {})
    if active:
        preferences = profile.preferences or {}
        if not preferences.get("company_career_boards"):
            raise HTTPException(409, "Add at least one Greenhouse or Lever company board before starting scheduled discovery")
    prefs["automation_active"] = active
    if active and prefs.get("mode") == "AUTO_APPLY":
        prefs["mode"] = "ASSISTED"  # No connector has been approved/configured for hands-free submission.
        prefs["auto_apply_enabled"] = False
    profile.application_preferences = prefs
    db.add(AutomationTask(user_id=user.id, task_type="COMPANY_CAREER_DISCOVERY", status="SCHEDULED" if active else "CANCELLED", payload={"providers": ["greenhouse", "lever"], "read_only": True}))
    _audit(db, user.id, "AUTOMATION_STARTED" if active else "AUTOMATION_STOPPED", "automation")
    db.commit()
    return {"active": active, "mode": prefs.get("mode", "ASSISTED"), "auto_apply_enabled": prefs.get("auto_apply_enabled", False), "message": "Read-only company-board refresh is scheduled every six hours when the worker or scheduled trigger is deployed. Applications still require manual completion."}


@router.post("/automation/start")
def start_automation(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return set_automation(True, user, db)


@router.post("/automation/stop")
def stop_automation(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return set_automation(False, user, db)


@router.patch("/preferences")
def patch_preferences(payload: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if not profile:
        profile = Profile(user_id=user.id)
        db.add(profile)
    current = dict(profile.preferences or {})
    current.update(payload)
    profile.preferences = current
    if "minimum_match_score" in payload:
        application_preferences = dict(profile.application_preferences or {})
        application_preferences["review_threshold"] = max(0, min(100, float(payload["minimum_match_score"])))
        profile.application_preferences = application_preferences
    db.commit()
    return current


@router.get("/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(desc(Notification.created_at)).limit(100)).all()
    return [{"id": str(x.id), "kind": x.kind, "title": x.title, "body": x.body, "link": x.link, "read": x.read, "created_at": x.created_at} for x in rows]


@router.patch("/notifications/{notification_id}")
def update_notification(notification_id: UUID, payload: NotificationReadInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id))
    if not row:
        raise HTTPException(404, "Notification not found")
    row.read = payload.read
    db.commit()
    return {"id": str(row.id), "read": row.read}


@router.post("/notifications/read-all")
def mark_all_notifications_read(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read.is_(False))).all()
    for row in rows:
        row.read = True
    db.commit()
    return {"updated": len(rows)}


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    jobs = db.scalars(select(Job)).all()
    matches = db.scalars(select(JobMatch).where(JobMatch.user_id == user.id)).all()
    apps = db.scalars(select(Application).where(Application.user_id == user.id)).all()
    today = datetime.now(timezone.utc).date()
    submitted = [a for a in apps if a.status == ApplicationStatus.SUBMITTED]
    pending = [a for a in apps if a.status == ApplicationStatus.MANUAL_ACTION_REQUIRED]
    scores = [m.match_score for m in matches]
    return {"jobs_discovered": len(jobs), "jobs_matched": sum(m.match_score >= 70 for m in matches), "applications_submitted": len(submitted), "applications_today": sum(bool(a.submitted_at and a.submitted_at.date() == today) for a in submitted), "pending_actions": len(pending), "failed_applications": sum(a.status == ApplicationStatus.FAILED for a in apps), "average_match_score": round(sum(scores) / len(scores), 1) if scores else 0, "high_match_jobs": sum(m.match_score >= 85 for m in matches)}
