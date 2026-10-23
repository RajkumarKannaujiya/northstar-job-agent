from app.platforms.mock import MOCK_JOBS


SUPPORTED_PLATFORMS = ("naukri", "indeed", "linkedin", "apna", "foundit", "internshala", "wellfound", "cutshort", "shine", "timesjobs", "glassdoor", "company_careers", "mock")


def get_adapter(platform: str):
    if platform == "mock":
        return MockJobPortal()
    raise NotImplementedError(f"No permitted adapter is configured for {platform}")


class MockJobPortal:
    """Deterministic synthetic portal for development and tests; never contacts real job sites."""
    platform = "mock"

    async def authenticate(self): return {"authenticated": True, "mode": "synthetic"}
    async def search_jobs(self, query: dict): return MOCK_JOBS
    async def get_job_details(self, platform_job_id: str): return next((j for j in MOCK_JOBS if j["platform_job_id"] == platform_job_id), {})
    def normalize_job(self, raw: dict): return dict(raw)
    async def detect_application_type(self, job: dict): return job.get("application_type", "MANUAL")
    async def get_application_form(self, job: dict): return [{"label": "Tell us about yourself", "type": "textarea", "required": True}, {"label": "Years of experience", "type": "text", "required": True}, {"label": "Unknown validation question", "type": "text", "required": True}]
    async def fill_application_form(self, fields: list[dict], answers: dict): return {"filled": [], "requires_user_input": [field for field in fields if field.get("label") not in answers]}
    async def upload_resume(self, application: dict, resume_path: str): return {"uploaded": bool(resume_path), "verified": False}
    async def submit_application(self, application: dict): return {"submitted": False, "status": "MANUAL_ACTION_REQUIRED", "reason": "Mock connector never submits"}
    async def get_application_status(self, application_id: str): return {"status": "UNKNOWN"}
    async def logout(self): return None
    async def health_check(self): return {"healthy": True, "synthetic": True}
