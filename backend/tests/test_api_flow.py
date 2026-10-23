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


def test_reanalyze_jobs_uses_current_saved_titles(client):
    token = register(client)
    headers = {"Authorization": f"Bearer {token}"}
    with TestSession() as db:
        from app.models import User
        user = db.query(User).filter_by(email="candidate@example.com").one()
        db.add(Resume(user_id=user.id, filename="candidate.txt", content_type="text/plain", storage_key="synthetic-only", parsed_data={"skills": ["SQL"], "explicit_skills": ["SQL"], "years_of_experience": 1, "experience": []}, extracted_text="synthetic fixture"))
        db.commit()
    job = client.post("/api/jobs", headers=headers, json={"platform": "mock", "platform_job_id": "reanalyze-1", "title": "Data Analyst", "company": "Example", "location": "Surat", "skills": ["SQL"], "application_url": "https://example.com/jobs/1"})
    assert job.status_code == 201, job.text
    initial = client.post(f"/api/jobs/{job.json()['id']}/analyze", headers=headers)
    assert initial.status_code == 200, initial.text
    updated_profile = client.put("/api/profile", headers=headers, json={"professional": {"target_job_titles": ["Data Analyst"]}})
    assert updated_profile.status_code == 200, updated_profile.text
    result = client.post("/api/jobs/reanalyze", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["count"] == 1
    refreshed = client.get("/api/jobs", headers=headers).json()[0]
    assert refreshed["match"]["score"] > initial.json()["match_score"]


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
    extracted_profile = client.get("/api/profile", headers=headers).json()
    assert extracted_profile["personal"]["full_name"] == "Mira Shah"
    assert extracted_profile["personal"]["email"] == "mira@example.com"
    assert "python" in extracted_profile["professional"]["skills"]
    assert resume["is_preferred"] is True
    download = client.get(f"/api/resumes/{resume['id']}/download", headers=headers)
    assert download.status_code == 200
    assert download.content == b"Mira Shah\nmira@example.com\nSKILLS\nPython, SQL"
    preferred = client.put(f"/api/resumes/{resume['id']}/preferred", headers=headers)
    assert preferred.status_code == 200
    assert preferred.json()["is_preferred"] is True
    with TestSession() as db:
        from app.models import ResumeVersion, ResumeSkill
        assert db.query(ResumeVersion).filter_by(resume_id=UUID(resume["id"])).count() == 1
        assert db.query(ResumeSkill).filter(ResumeSkill.resume_id == UUID(resume["id"])).count() == 2
    deleted = client.delete(f"/api/resumes/{resume['id']}", headers=headers)
    assert deleted.status_code == 204
    assert not list(tmp_path.glob("*.enc"))


def test_account_export_notification_read_and_deletion(client, tmp_path, monkeypatch):
    token = register(client)
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "environment", "development")
    uploaded = client.post("/api/resumes/upload", headers=headers, files={"file": ("candidate.txt", b"Candidate\ncandidate@example.com\nSKILLS\nPython", "text/plain")})
    assert uploaded.status_code == 201, uploaded.text
    assert client.put("/api/profile", headers=headers, json={"personal": {"full_name": "Candidate"}}).status_code == 200
    assert client.post("/api/jobs/discover-mock", headers=headers).status_code == 200

    notice = client.get("/api/notifications", headers=headers).json()[0]
    marked = client.patch(f"/api/notifications/{notice['id']}", headers=headers, json={"read": True})
    assert marked.status_code == 200 and marked.json()["read"] is True
    assert client.post("/api/notifications/read-all", headers=headers).status_code == 200

    exported = client.get("/api/me/export", headers=headers)
    assert exported.status_code == 200
    assert exported.json()["account"]["email"] == "candidate@example.com"
    assert len(exported.json()["resumes"]) == 1
    assert exported.json()["profile"]["personal"]["full_name"] == "Candidate"

    erased = client.delete("/api/me", headers=headers)
    assert erased.status_code == 204
    assert not list(tmp_path.glob("*.enc"))
    assert client.get("/api/me", headers=headers).status_code == 401
    with TestSession() as db:
        from app.models import User, Profile, Resume, Notification, AuditLog
        assert db.query(User).filter_by(email="candidate@example.com").count() == 0
        assert db.query(Profile).count() == 0
        assert db.query(Resume).count() == 0
        assert db.query(Notification).count() == 0
        assert db.query(AuditLog).count() == 0


def test_company_career_boards_are_read_only_and_can_be_scheduled(client, monkeypatch):
    token = register(client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"boards": [{"provider": "greenhouse", "board_token": "sample-company", "company_name": "Sample Company"}]}
    saved = client.put("/api/platforms/company-careers", headers=headers, json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["boards"] == payload["boards"]

    from app.api import routes
    async def fake_fetch(provider, board_token, company_name):
        return [{"platform": provider, "platform_job_id": f"{board_token}:100", "title": "Data Analyst", "company": company_name, "location": "Surat", "remote_type": "UNKNOWN", "salary_min": None, "salary_max": None, "currency": None, "experience_min": None, "experience_max": None, "skills": ["SQL"], "description": "SQL reporting", "requirements": [], "benefits": [], "employment_type": "UNKNOWN", "posted_at": datetime.now(timezone.utc), "application_url": "https://boards.greenhouse.io/sample-company/jobs/100", "application_type": "MANUAL", "recruiter": None, "source_url": "https://boards.greenhouse.io/sample-company/jobs/100"}]
    monkeypatch.setattr(routes, "fetch_board", fake_fetch)

    discovered = client.post("/api/jobs/discover-company-careers", headers=headers)
    assert discovered.status_code == 200, discovered.text
    assert discovered.json()["new"] == 1
    assert discovered.json()["mode"] == "read_only_public_jobs"
    assert client.get("/api/platforms", headers=headers).json()[-2]["automation_available"] is True
    start = client.post("/api/automation/start", headers=headers)
    assert start.status_code == 200, start.text
    assert start.json()["active"] is True

    jobs = client.get("/api/jobs", headers=headers).json()
    assert jobs[0]["application_type"] == "MANUAL"
    assert jobs[0]["sources"][0]["platform"] == "greenhouse"


def test_live_discovery_imports_and_ranks_public_feeds_with_cooldown(client, tmp_path, monkeypatch):
    from app.platforms.public_feeds import clear_public_feed_cache
    clear_public_feed_cache()
    token = register(client)
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "environment", "development")
    uploaded = client.post(
        "/api/resumes/upload",
        headers=headers,
        files={"file": ("candidate.txt", b"Candidate\nSKILLS\nExcel, SQL", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text

    from app.api import routes
    calls = {"remoteok": 0, "remotive": 0}

    def listing(provider, job_id):
        return {
            "platform": provider,
            "platform_job_id": job_id,
            "title": "Data Analyst",
            "company": f"{provider} Example",
            "location": "Worldwide Remote",
            "remote_type": "REMOTE",
            "salary_min": None,
            "salary_max": None,
            "currency": None,
            "experience_min": None,
            "experience_max": None,
            "skills": ["Excel", "SQL"],
            "description": "Analyze reports using Excel and SQL.",
            "requirements": [],
            "benefits": [],
            "employment_type": "FULL_TIME",
            "posted_at": datetime.now(timezone.utc),
            "application_url": f"https://{provider}.example/jobs/{job_id}",
            "application_type": "MANUAL",
            "recruiter": None,
            "source_url": f"https://{provider}.example/jobs/{job_id}",
        }

    async def fetch_remoteok():
        calls["remoteok"] += 1
        return [listing("remoteok", "live-1")]

    async def fetch_remotive():
        calls["remotive"] += 1
        return [listing("remotive", "live-2")]

    monkeypatch.setattr(routes, "fetch_remoteok", fetch_remoteok)
    monkeypatch.setattr(routes, "fetch_remotive", fetch_remotive)

    response = client.post("/api/jobs/discover-live", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 2
    assert response.json()["new"] == 2
    assert response.json()["resume_used_for_matching"] is True
    assert response.json()["resume_sent_to_feeds"] is False
    jobs = client.get("/api/jobs", headers=headers).json()
    assert {source["platform"] for job in jobs for source in job["sources"]} == {"remoteok", "remotive"}
    assert all(job["match"] and job["match"]["score"] > 0 for job in jobs)
    assert client.get("/api/applications", headers=headers).json() == []

    cached = client.post("/api/jobs/discover-live", headers=headers)
    assert cached.status_code == 200
    assert all(feed["status"] == "cached" for feed in cached.json()["feeds"])
    assert calls == {"remoteok": 1, "remotive": 1}


def test_scheduled_discovery_requires_secret_and_only_processes_opted_in_users(client, monkeypatch):
    from app.platforms.public_feeds import clear_public_feed_cache
    clear_public_feed_cache()
    token = register(client)
    headers = {"Authorization": f"Bearer {token}"}
    saved = client.put("/api/platforms/company-careers", headers=headers, json={"boards": [{"provider": "lever", "board_token": "sample-company", "company_name": "Sample Company"}]})
    assert saved.status_code == 200
    started = client.post("/api/automation/start", headers=headers)
    assert started.status_code == 200 and started.json()["active"] is True

    secret = "test-only-scheduler-secret-32-chars-long"
    monkeypatch.setattr(settings, "scheduler_shared_secret", secret)
    unauthorized = client.post("/api/internal/scheduled-discovery")
    assert unauthorized.status_code == 404

    from app.api import routes
    async def no_jobs(provider, board_token, company_name):
        return []

    async def no_public_jobs():
        return []

    monkeypatch.setattr(routes, "fetch_board", no_jobs)
    monkeypatch.setattr(routes, "fetch_remoteok", no_public_jobs)
    monkeypatch.setattr(routes, "fetch_remotive", no_public_jobs)
    response = client.post("/api/internal/scheduled-discovery", headers={"X-Scheduler-Secret": secret})
    assert response.status_code == 200, response.text
    assert response.json()["processed"] == 1
    assert len(response.json()["users"]) == 1
    assert response.json()["users"][0]["status"] == "ok"
    assert response.json()["users"][0]["new"] == 0
    assert response.json()["users"][0]["seen"] == 0
    assert "user_id" not in response.json()["users"][0]
