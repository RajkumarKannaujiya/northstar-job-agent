import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


JsonType = JSON().with_variant(JSONB, "postgresql")


class ApplicationStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    ANALYZING = "ANALYZING"
    MATCHED = "MATCHED"
    ELIGIBLE = "ELIGIBLE"
    APPLICATION_STARTED = "APPLICATION_STARTED"
    FORM_ANALYZING = "FORM_ANALYZING"
    FORM_FILLED = "FORM_FILLED"
    RESUME_UPLOADED = "RESUME_UPLOADED"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTED = "SUBMITTED"
    MANUAL_ACTION_REQUIRED = "MANUAL_ACTION_REQUIRED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ASSESSMENT = "ASSESSMENT"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    resumes: Mapped[list["Resume"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    personal: Mapped[dict] = mapped_column(JsonType, default=dict)
    professional: Mapped[dict] = mapped_column(JsonType, default=dict)
    education: Mapped[dict] = mapped_column(JsonType, default=dict)
    preferences: Mapped[dict] = mapped_column(JsonType, default=dict)
    application_preferences: Mapped[dict] = mapped_column(JsonType, default=dict)
    answer_bank: Mapped[list] = mapped_column(JsonType, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    user: Mapped[User] = relationship(back_populates="profile")


class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    storage_key: Mapped[str] = mapped_column(String(80), unique=True)
    parsed_data: Mapped[dict] = mapped_column(JsonType, default=dict)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    user: Mapped[User] = relationship(back_populates="resumes")


class ResumeVersion(Base):
    __tablename__ = "resume_versions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    resume_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(80))
    parsed_data: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (UniqueConstraint("resume_id", "version", name="uq_resume_version"),)


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    canonical_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(40), default="technical")
    parent_skill_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"))


class ResumeSkill(Base):
    __tablename__ = "resume_skills"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    resume_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(20), default="EXPLICIT")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    evidence: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("resume_id", "skill_id", name="uq_resume_skill"),)


class JobSource(Base):
    __tablename__ = "job_sources"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(32), default="DISCONNECTED")
    automation_available: Mapped[bool] = mapped_column(Boolean, default=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (UniqueConstraint("user_id", "platform", name="uq_user_platform"),)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    canonical_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    company: Mapped[str] = mapped_column(String(300), index=True)
    location: Mapped[str] = mapped_column(String(300), default="")
    remote_type: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(8))
    experience_min: Mapped[float | None] = mapped_column(Float)
    experience_max: Mapped[float | None] = mapped_column(Float)
    skills: Mapped[list] = mapped_column(JsonType, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    requirements: Mapped[list] = mapped_column(JsonType, default=list)
    benefits: Mapped[list] = mapped_column(JsonType, default=list)
    employment_type: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    application_url: Mapped[str] = mapped_column(Text)
    application_type: Mapped[str] = mapped_column(String(40), default="EXTERNAL")
    recruiter: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    sources: Mapped[list["JobSourceMapping"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_job_company_title_location", "company", "title", "location"),)


class JobSourceMapping(Base):
    __tablename__ = "job_sources_mapping"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(80))
    platform_job_id: Mapped[str] = mapped_column(String(300))
    source_url: Mapped[str] = mapped_column(Text)
    job: Mapped[Job] = relationship(back_populates="sources")
    __table_args__ = (UniqueConstraint("platform", "platform_job_id", name="uq_platform_job"),)


class JobSkill(Base):
    __tablename__ = "job_skills"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    requirement_type: Mapped[str] = mapped_column(String(20), default="REQUIRED")
    __table_args__ = (UniqueConstraint("job_id", "skill_id", name="uq_job_skill"),)


class JobMatch(Base):
    __tablename__ = "job_matches"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    manual_resume_override: Mapped[bool] = mapped_column(Boolean, default=False)
    match_score: Mapped[float] = mapped_column(Float)
    breakdown: Mapped[dict] = mapped_column(JsonType, default=dict)
    reasons: Mapped[list] = mapped_column(JsonType, default=list)
    missing: Mapped[list] = mapped_column(JsonType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_user_job_match"),)


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(80))
    resume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    match_score: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[ApplicationStatus] = mapped_column(Enum(ApplicationStatus, native_enum=False), default=ApplicationStatus.DISCOVERED)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    application_url: Mapped[str] = mapped_column(Text)
    confirmation_text: Mapped[str | None] = mapped_column(Text)
    confirmation_reference: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_user_application_job"),)


class ApplicationQuestion(Base):
    __tablename__ = "application_questions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(40))
    answer: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    answer_source: Mapped[str | None] = mapped_column(String(40))
    requires_user_input: Mapped[bool] = mapped_column(Boolean, default=True)


class ApplicationAnswer(Base):
    __tablename__ = "application_answers"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    question_key: Mapped[str] = mapped_column(String(300))
    answer: Mapped[str] = mapped_column(Text)
    answer_source: Mapped[str] = mapped_column(String(40), default="user_entered")
    verified: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JsonType, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PlatformAccount(Base):
    __tablename__ = "platform_accounts"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(80))
    encrypted_secret: Mapped[str | None] = mapped_column(Text)
    auth_type: Mapped[str] = mapped_column(String(40), default="OFFICIAL_OAUTH")
    status: Mapped[str] = mapped_column(String(32), default="DISCONNECTED")


class AutomationTask(Base):
    __tablename__ = "automation_tasks"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="QUEUED")
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SystemError(Base):
    __tablename__ = "system_errors"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    component: Mapped[str] = mapped_column(String(120))
    error_code: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
