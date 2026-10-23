from typing import Protocol, Any

from app.services.matching import score_job
from app.services.questions import answer_from_verified_sources, classify_question
from app.services.resume_parser import parse_resume


class AIProvider(Protocol):
    def parse_resume(self, text: str) -> dict[str, Any]: ...
    def analyze_job(self, job: dict, resume: dict, profile: dict) -> dict[str, Any]: ...
    def calculate_semantic_match(self, job: dict, resume: dict) -> float: ...
    def generate_application_answer(self, question: str, profile: dict, resume: dict, answer_bank: list[dict]) -> dict[str, Any]: ...
    def select_resume(self, job: dict, resumes: list[dict], profile: dict) -> dict[str, Any] | None: ...
    def classify_question(self, question: str) -> str: ...
    def generate_cover_letter(self, job: dict, profile: dict, resume: dict) -> dict[str, Any]: ...
    def detect_risk(self, job: dict, form_text: str = "") -> list[str]: ...


class RuleBasedProvider:
    """Offline provider that only returns supported facts; replace with a vetted model adapter as needed."""
    def parse_resume(self, text: str) -> dict[str, Any]:
        return parse_resume(text)

    def analyze_job(self, job: dict, resume: dict, profile: dict) -> dict[str, Any]:
        return score_job(job, resume, profile)

    def calculate_semantic_match(self, job: dict, resume: dict) -> float:
        return score_job(job, resume).get("breakdown", {}).get("semantic", 0.0)

    def generate_application_answer(self, question: str, profile: dict, resume: dict, answer_bank: list[dict]) -> dict[str, Any]:
        return answer_from_verified_sources(question, profile, resume, answer_bank)

    def select_resume(self, job: dict, resumes: list[dict], profile: dict) -> dict[str, Any] | None:
        if not resumes:
            return None
        return max(resumes, key=lambda item: score_job(job, item.get("parsed_data", {}), profile)["match_score"])

    def classify_question(self, question: str) -> str:
        return classify_question(question)

    def generate_cover_letter(self, job: dict, profile: dict, resume: dict) -> dict[str, Any]:
        # Free text is not generated from weak evidence; callers must review and supply verified highlights.
        return {"text": None, "requires_user_input": True, "reason": "Add verified role-specific highlights before generating a cover letter."}

    def detect_risk(self, job: dict, form_text: str = "") -> list[str]:
        flags = []
        if any(token in form_text.lower() for token in ("captcha", "one-time password", "otp", "multi-factor", "mfa")):
            flags.append("MANUAL_AUTHENTICATION_REQUIRED")
        if not job.get("application_url", "").startswith("https://"):
            flags.append("NON_HTTPS_APPLICATION_URL")
        if not job.get("posted_at"):
            flags.append("POSTING_DATE_UNKNOWN")
        return flags
