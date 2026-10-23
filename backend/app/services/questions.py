import re


def classify_question(question: str) -> str:
    q = question.lower()
    if any(x in q for x in ("visa", "work authorization", "legally authorized", "criminal", "disability", "gender", "race", "ethnicity")): return "LEGAL" if any(x in q for x in ("visa", "authorized", "criminal")) else "DEMOGRAPHIC"
    if any(x in q for x in ("salary", "compensation", "expected pay")): return "SALARY"
    if any(x in q for x in ("relocate", "location", "commute", "onsite", "remote")): return "LOCATION"
    if any(x in q for x in ("years of experience", "how many years", "degree", "certification", "skill", "experience with")): return "RESUME_FACT"
    if any(x in q for x in ("why should we hire", "tell us about yourself", "why this role")): return "JOB_SPECIFIC"
    if any(x in q for x in ("notice period", "start date", "willing")): return "PREFERENCE"
    return "UNKNOWN"


def answer_from_verified_sources(question: str, profile: dict, resume: dict, answer_bank: list[dict]) -> dict:
    normalized = re.sub(r"[^a-z0-9]+", " ", question.lower()).strip()
    for item in answer_bank:
        key = re.sub(r"[^a-z0-9]+", " ", item.get("question", "").lower()).strip()
        if key and (key == normalized or key in normalized or normalized in key):
            return {"answer": item.get("answer"), "confidence": 1.0, "source": "saved_answer", "requires_user_input": False}
    qtype = classify_question(question)
    personal = profile.get("personal", {})
    professional = profile.get("professional", {})
    prefs = profile.get("preferences", {})
    explicit_skills = {str(skill).casefold() for skill in resume.get("explicit_skills", resume.get("skills", []))}
    explicit_skills.update(str(skill).casefold() for skill in professional.get("skills", []))
    mentioned_skills = [skill for skill in explicit_skills if skill and skill in normalized]
    if qtype == "SALARY": value = prefs.get("preferred_salary") or prefs.get("minimum_salary") or profile.get("preferred_salary") or profile.get("minimum_salary")
    elif qtype == "LOCATION": value = prefs.get("relocation_preference") or ("Yes" if prefs.get("relocation_allowed") else "No" if prefs.get("relocation_allowed") is False else None)
    elif "experience" in normalized and "years" in normalized:
        value = None if mentioned_skills else resume.get("years_of_experience")
        if value == 0:
            value = None
    elif "experience with" in normalized or "experience in" in normalized:
        if mentioned_skills and not re.search(r"\b\d+(?:\.\d+)?\s+years?\b", normalized):
            return {"answer": "Yes", "confidence": 0.9, "source": "resume", "requires_user_input": False}
        value = None
    elif "email" in normalized: value = personal.get("email")
    elif "phone" in normalized: value = personal.get("phone")
    elif "name" in normalized: value = personal.get("full_name") or resume.get("name")
    elif "linkedin" in normalized: value = professional.get("linkedin_url")
    else: value = None
    if value is not None:
        return {"answer": str(value), "confidence": 0.95, "source": "user_profile" if value in personal.values() or value in professional.values() else "resume", "requires_user_input": False}
    return {"answer": None, "confidence": 0.0, "source": None, "requires_user_input": True}
