from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.models import Resume
from tests.conftest import TestSession
from app.core.config import settings


def register(client):
    response = client.post("/api/auth/register", json={"email": "candidate@example.com", "password": "SecurePassword123"})
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def test_manual_application_flow_requires_and_records_confirmation(client):
    token = register(client)
    headers = {"Authorization": f"Bearer {token}"}
    with TestSession() as db:
        from app.models import User
        user = db.query(User).filter_by(email="candidate@example.com").one()
        primary_resume = Resume(user_id=user.id, filename="candidate.txt", content_type="text/plain", storage_key="synthetic-only", parsed_data={"skills": ["SQL"], "explicit_skills": ["SQL"], "years_of_experience": 2, "experience": []}, extracted_text="synthetic fixture")
        db.add(primary_resume)
        db.flush()
        primary_id = str(primary_resume.id)
        db.add(Resume(user_id=user.id, filename="other.txt", content_type="text/plain", storage_key="synthetic-only-2", parsed_data={"skills": ["Figma"], "explicit_skills": ["Figma"], "years_of_experience": 1, "experience": []}, extracted_text="other synthetic fixture"))
        db.commit()
    profile = client.put("/api/profile", headers=headers, json={"personal": {"full_name": "Candidate"}, "professional": {"target_job_titles": ["Data Analyst"]}, "preferences": {"preferred_locations": ["Surat"], "minimum_salary": 400000}, "application_preferences": {"mode": "ASSISTED", "review_threshold": 50, "auto_apply_threshold": 85, "max_daily_applications": 10, "max_hourly_applications": 5, "max_applications_per_company": 2}})
    assert profile.status_code == 200
    job = client.post("/api/jobs", headers=headers, json={"platform": "mock", "platform_job_id": "synthetic-123", "title": "Data Analyst", "company": "Example Analytics", "location": "Surat, India", "salary_min": 500000, "salary_max": 650000, "currency": "INR", "skills": ["SQL"], "description": "Analyze data with SQL", "employment_type": "FULL_TIME", "posted_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "application_url": "https://example.com/job/123", "source_url": "https://example.com/job/123"})
    assert job.status_code == 201, job.text
    override = client.post(f"/api/jobs/{job.json()['id']}/resume", headers=headers, json={"resume_id": primary_id})
    assert override.status_code == 200, override.text
    assert override.json()["manual_override"] is True
    application = client.post("/api/applications", headers=headers, params={"job_id": job.json()["id"]})
    assert application.status_code == 201, application.text
    application_data = application.json()
    assert application_data["status"] == "MANUAL_ACTION_REQUIRED"
    assert application_data["application_url"] == "https://example.com/job/123"
    direct_submit = client.post(f"/api/applications/{application_data['id']}/transition", headers=headers, json={"target_status": "SUBMITTED"})
    assert direct_submit.status_code == 409
    confirmed = client.post(f"/api/applications/{application_data['id']}/confirm-submission", headers=headers, json={"confirmation_signal": "application_id", "confirmation_reference": "REF-123", "confirmation_text": "Application received"})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "SUBMITTED"
    details = client.get(f"/api/applications/{application_data['id']}", headers=headers).json()
    assert any(event["type"] == "APPLICATION_SUBMITTED" for event in details["events"])
    duplicate = client.post("/api/applications", headers=headers, params={"job_id": job.json()["id"]})
    assert duplicate.status_code == 409


def test_registration_rejects_weak_password(client):
    response = client.post("/api/auth/register", json={"email": "weak@example.com", "password": "short"})
    assert response.status_code == 422


def test_job_ingest_rejects_non_https_application_link(client):
    token = register(client)
    response = client.post("/api/jobs", headers={"Authorization": f"Bearer {token}"}, json={"platform": "manual", "platform_job_id": "unsafe", "title": "Role", "company": "Company", "application_url": "javascript:alert(1)"})
    assert response.status_code == 422


def test_resume_upload_is_encrypted_and_versioned(client, tmp_path, monkeypatch):
    token = register(client)
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "environment", "development")
    response = client.post("/api/resumes/upload", headers=headers, files={"file": ("candidate.txt", b"Mira Shah\nmira@example.com\nSKILLS\nPython, SQL", "text/plain")})
    assert response.status_code == 201, response.text
    resume = response.json()
    stored = list(tmp_path.glob("*.enc"))
    assert len(stored) == 1
    assert b"mira@example.com" not in stored[0].read_bytes()
    assert "python" in resume["parsed_data"]["explicit_skills"]
    with TestSession() as db:
        from app.models import ResumeVersion, ResumeSkill
        assert db.query(ResumeVersion).filter_by(resume_id=UUID(resume["id"])).count() == 1
        assert db.query(ResumeSkill).filter(ResumeSkill.resume_id == UUID(resume["id"])).count() == 2
    deleted = client.delete(f"/api/resumes/{resume['id']}", headers=headers)
    assert deleted.status_code == 204
    assert not list(tmp_path.glob("*.enc"))
