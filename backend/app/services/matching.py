import hashlib
import re
from datetime import datetime, timezone


DEFAULT_WEIGHTS = {
    "skills": 25, "experience": 20, "title": 15, "location": 10,
    "salary": 10, "semantic": 10, "employment": 5, "freshness": 5,
}


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def canonical_job_key(job: dict) -> str:
    normalized = "|".join(normalize_text(str(job.get(key, ""))) for key in ("company", "title", "location"))
    return hashlib.sha256(normalized.encode()).hexdigest()


def score_job(job: dict, resume: dict, profile: dict | None = None, weights: dict | None = None) -> dict:
    profile = profile or {}
    weights = weights or DEFAULT_WEIGHTS
    skill_set = {normalize_text(item) for item in resume.get("explicit_skills", resume.get("skills", []))}
    job_skills = {normalize_text(item) for item in job.get("skills", [])}
    hits = skill_set & job_skills
    skill_score = len(hits) / max(1, len(job_skills)) * 100 if job_skills else 50
    years = float(resume.get("years_of_experience") or 0)
    exp_min = job.get("experience_min")
    exp_max = job.get("experience_max")
    experience_score = 100 if exp_min is None and exp_max is None else (100 if (exp_min or 0) <= years <= (exp_max or 100) else max(0, 100 - abs(years - (exp_min or exp_max or years)) * 20))
    professional = profile.get("professional", {})
    preferences = profile.get("preferences", {})
    targets = [normalize_text(x) for x in professional.get("target_job_titles", profile.get("target_job_titles", []))]
    title = normalize_text(job.get("title", ""))
    title_score = 100 if any(t and (t in title or title in t) for t in targets) else (50 if not targets else 20)
    locations = [normalize_text(x) for x in preferences.get("preferred_locations", profile.get("preferred_locations", []))]
    loc = normalize_text(job.get("location", ""))
    location_score = 100 if not locations or any(x in loc for x in locations) or ("remote" in loc and preferences.get("remote_allowed", True)) else 0
    salary_floor = preferences.get("minimum_salary", profile.get("minimum_salary"))
    salary_max = job.get("salary_max")
    salary_score = 100 if salary_floor is None or salary_max is None or salary_max >= salary_floor else 0
    employment = preferences.get("employment_types", profile.get("employment_types", []))
    employment_score = 100 if not employment or job.get("employment_type") in employment else 0
    posted = job.get("posted_at")
    if isinstance(posted, str):
        try:
            posted = datetime.fromisoformat(posted.replace("Z", "+00:00"))
        except ValueError:
            posted = None
    if posted and posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    age_hours = max(0, (datetime.now(timezone.utc) - posted.astimezone(timezone.utc)).total_seconds() / 3600) if posted else None
    freshness_score = 100 if age_hours is not None and age_hours <= 2 else max(0, 100 - (age_hours or 168) / 168 * 100)
    # Offline semantic proxy only. A configured embedding provider can replace this component.
    desc_words = set(normalize_text(job.get("description", "")).split())
    resume_words = set(normalize_text(" ".join(resume.get("skills", [])) + " " + " ".join(str(x.get("text", "")) for x in resume.get("experience", []))).split())
    semantic_score = len(desc_words & resume_words) / max(1, min(len(desc_words), 50)) * 100
    components = {
        "skills": skill_score, "experience": experience_score, "title": title_score,
        "location": location_score, "salary": salary_score, "semantic": min(100, semantic_score),
        "employment": employment_score, "freshness": freshness_score,
    }
    denominator = sum(weights.values()) or 1
    overall = round(sum(components[name] * weights.get(name, 0) for name in components) / denominator, 1)
    reasons = [f"{skill} matches an explicitly listed resume skill" for skill in sorted(hits)]
    if location_score == 100: reasons.append("Location matches configured preferences")
    if experience_score == 100: reasons.append("Experience range is compatible")
    missing = sorted(job_skills - skill_set)
    return {"match_score": overall, "breakdown": {k: round(v, 1) for k, v in components.items()}, "reasons": reasons, "missing": missing, "selected_resume_reason": "Highest score across available resumes"}
