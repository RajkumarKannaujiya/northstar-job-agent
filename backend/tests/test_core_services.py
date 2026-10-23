from datetime import datetime, timedelta, timezone

from app.models import ApplicationStatus
from app.platforms.browser import FormDetector
from app.services.decisions import decide_application
from app.services.matching import canonical_job_key, score_job
from app.services.questions import answer_from_verified_sources, classify_question
from app.services.resume_parser import extract_text, parse_resume
from app.services.transitions import transition
from app.platforms.career_pages import fetch_board, normalize_greenhouse, normalize_lever, validate_board
from app.core import storage
from app.core.config import settings
from cryptography.fernet import Fernet


def test_resume_parser_only_marks_observed_skills_explicit():
    parsed = parse_resume("""Riya Patel
riya@example.com | +91 98765 43210 | Surat, India
SKILLS
Python, SQL, Excel
EXPERIENCE
Data Analyst, Sample Analytics, 2021-2024
EDUCATION
B.Sc Statistics, 2020
""")
    assert parsed["name"] == "Riya Patel"
    assert parsed["email"] == "riya@example.com"
    assert {"python", "sql", "excel"}.issubset(parsed["explicit_skills"])
    assert parsed["inferred_skills"] == []
    assert parsed["years_of_experience"] == 3


def test_docx_and_pdf_text_extraction_handles_synthetic_documents():
    import io
    from docx import Document
    from pypdf import PdfWriter

    doc = Document()
    doc.add_paragraph("Candidate skills: SQL and Excel")
    docx_bytes = io.BytesIO()
    doc.save(docx_bytes)
    assert "SQL and Excel" in extract_text("resume.docx", docx_bytes.getvalue())

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    pdf_bytes = io.BytesIO()
    writer.write(pdf_bytes)
    assert extract_text("resume.pdf", pdf_bytes.getvalue()) == ""


def test_match_explains_supported_skills_and_missing_skills():
    job = {"company": "A", "title": "Data Analyst", "location": "Surat", "skills": ["SQL", "Power BI"], "description": "SQL reports", "posted_at": datetime.now(timezone.utc)}
    resume = {"skills": ["SQL"], "explicit_skills": ["SQL"], "years_of_experience": 2, "experience": []}
    result = score_job(job, resume, {"professional": {"target_job_titles": ["Data Analyst"]}, "preferences": {"preferred_locations": ["Surat"]}})
    assert result["match_score"] > 50
    assert result["reasons"] == ["sql matches an explicitly listed resume skill", "Location matches configured preferences", "Experience range is compatible"]
    assert result["missing"] == ["power bi"]


def test_deduplication_uses_canonical_company_title_location():
    first = {"company": "Sample Co.", "title": "Data Analyst", "location": "Surat, India"}
    duplicate = {"company": "sample co", "title": "Data Analyst!", "location": "Surat India"}
    assert canonical_job_key(first) == canonical_job_key(duplicate)


def test_auto_apply_is_not_eligible_without_permitted_connector():
    job = {"posted_at": datetime.now(timezone.utc), "salary_max": 700000}
    profile = {"application_preferences": {"mode": "AUTO_APPLY", "auto_apply_threshold": 80}, "preferences": {"minimum_salary": 400000}}
    result = decide_application(job, 92, profile, connector_supports_application=False)
    assert result["decision"] == "MANUAL_ACTION_REQUIRED"


def test_auto_apply_requires_explicit_enabled_setting():
    job = {"posted_at": datetime.now(timezone.utc), "salary_max": 700000, "location": "Remote India"}
    profile = {"application_preferences": {"mode": "AUTO_APPLY", "auto_apply_enabled": False, "auto_apply_threshold": 80}, "preferences": {"minimum_salary": 400000}}
    result = decide_application(job, 92, profile, connector_supports_application=True)
    assert result["decision"] == "REVIEW_REQUIRED"


def test_unknown_and_unverified_questions_never_get_guessed():
    assert classify_question("What is your national insurance number?") == "UNKNOWN"
    result = answer_from_verified_sources("Do you have 10 years of Kubernetes experience?", {}, {"skills": ["python"]}, [])
    assert result["answer"] is None
    assert result["requires_user_input"] is True
    years = answer_from_verified_sources("How many years of experience with SQL?", {}, {"explicit_skills": ["SQL"], "years_of_experience": 5}, [])
    assert years["answer"] is None
    assert years["requires_user_input"] is True
    simple_skill = answer_from_verified_sources("Do you have experience with SQL?", {}, {"explicit_skills": ["SQL"]}, [])
    assert simple_skill["answer"] == "Yes"


def test_submission_state_requires_confirmation():
    try:
        transition(ApplicationStatus.MANUAL_ACTION_REQUIRED, ApplicationStatus.SUBMITTED)
        assert False, "expected confirmation guard"
    except ValueError as exc:
        assert "verified platform confirmation" in str(exc)
    transition(ApplicationStatus.MANUAL_ACTION_REQUIRED, ApplicationStatus.SUBMITTED, confirmed_submission=True)


def test_captcha_or_mfa_stops_browser_work():
    detector = FormDetector()
    assert detector.detect_manual_challenge("Please verify you are human")
    assert detector.detect_manual_challenge("Enter your one-time password")
    assert not detector.detect_manual_challenge("Tell us about your work experience")


def test_company_career_adapters_normalize_public_jobs_and_keep_submission_manual():
    greenhouse = normalize_greenhouse({"id": 42, "title": "Data Analyst", "updated_at": "2026-10-22T12:00:00Z", "location": {"name": "Surat"}, "absolute_url": "https://boards.greenhouse.io/demo/jobs/42", "content": "<p>Use SQL and Excel</p><script>ignore()</script>"}, board_token="demo", company_name="Demo Co")
    assert greenhouse["platform"] == "greenhouse"
    assert greenhouse["skills"] == ["excel", "sql"]
    assert "ignore" not in greenhouse["description"]
    assert greenhouse["application_type"] == "MANUAL"
    assert greenhouse["application_url"].startswith("https://")

    unsafe_greenhouse = normalize_greenhouse({"id": 43, "absolute_url": "http://evil.example/apply"}, board_token="demo", company_name="Demo Co")
    assert unsafe_greenhouse["application_url"] == "https://boards.greenhouse.io/demo/jobs/43"

    lever = normalize_lever({"id": "abc", "text": "Backend Engineer", "createdAt": 1792670400000, "categories": {"location": "Remote India", "commitment": "Full-time"}, "descriptionPlain": "Python, FastAPI", "workplaceType": "remote", "hostedUrl": "https://jobs.lever.co/demo/abc", "salaryRange": {"min": 500000, "max": 800000, "currency": "INR"}}, board_token="demo", company_name="Demo Co")
    assert lever["remote_type"] == "REMOTE"
    assert lever["salary_min"] == 500000
    assert lever["employment_type"] == "FULL_TIME"
    assert lever["application_type"] == "MANUAL"
    unsafe_lever = normalize_lever({"id": "def", "hostedUrl": "https://evil.example/apply"}, board_token="demo", company_name="Demo Co")
    assert unsafe_lever["application_url"] == "https://jobs.lever.co/demo/def"
    try:
        validate_board("lever", "demo/../../evil.example")
        assert False, "invalid board token should be rejected"
    except ValueError:
        pass


def test_company_career_fetch_uses_fixed_official_host_and_normalizes_response():
    import asyncio
    import httpx

    async def run():
        seen = []

        async def handler(request):
            seen.append(str(request.url))
            return httpx.Response(200, json={"jobs": [{"id": 7, "title": "Analyst", "location": {"name": "Surat"}, "absolute_url": "https://boards.greenhouse.io/demo/jobs/7", "content": "SQL"}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            rows = await fetch_board("greenhouse", "demo", "Demo Co", client)
        assert len(rows) == 1
        assert rows[0]["platform_job_id"] == "demo:7"
        assert rows[0]["company"] == "Demo Co"
        assert seen[0].startswith("https://boards-api.greenhouse.io/")

    asyncio.run(run())


def test_resume_storage_encrypts_and_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "file_encryption_key", Fernet.generate_key().decode())
    key = storage.save_encrypted(b"private resume sample", ".txt")
    on_disk = (tmp_path / key).read_bytes()
    assert b"private resume sample" not in on_disk
    assert storage.read_encrypted(key) == b"private resume sample"
    storage.delete_encrypted(key)
    assert not (tmp_path / key).exists()


def test_s3_resume_storage_encrypts_before_upload_and_round_trips(monkeypatch):
    class Body:
        def __init__(self, value): self.value = value
        def read(self): return self.value

    class FakeS3:
        def __init__(self): self.objects = {}
        def put_object(self, *, Bucket, Key, Body): self.objects[(Bucket, Key)] = Body
        def get_object(self, *, Bucket, Key): return {"Body": Body(self.objects[(Bucket, Key)])}
        def delete_object(self, *, Bucket, Key): self.objects.pop((Bucket, Key), None)

    fake = FakeS3()
    monkeypatch.setattr(storage, "_s3_client", lambda: fake)
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "private-test-bucket")
    monkeypatch.setattr(settings, "file_encryption_key", Fernet.generate_key().decode())
    key = storage.save_encrypted(b"private candidate data", ".pdf")
    uploaded = fake.objects[("private-test-bucket", key)]
    assert b"private candidate data" not in uploaded
    assert storage.read_encrypted(key) == b"private candidate data"
    storage.delete_encrypted(key)
    assert not fake.objects
