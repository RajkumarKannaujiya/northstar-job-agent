from datetime import datetime, timezone


def decide_application(job: dict, score: float, profile: dict, connector_supports_application: bool) -> dict:
    prefs = profile.get("application_preferences", {})
    preferences = profile.get("preferences", {})
    blocked_companies = {str(x).casefold() for x in preferences.get("excluded_companies", [])}
    if job.get("company", "").casefold() in blocked_companies:
        return {"decision": "SKIP", "reasons": ["Company is excluded by user preferences"]}
    excluded_keywords = {str(x).casefold() for x in preferences.get("excluded_keywords", [])}
    if any(keyword and keyword in f"{job.get('title', '')} {job.get('description', '')}".casefold() for keyword in excluded_keywords):
        return {"decision": "SKIP", "reasons": ["Job contains an excluded keyword"]}
    mode = prefs.get("mode", "ASSISTED")
    min_score = float(prefs.get("auto_apply_threshold", 85))
    min_salary = preferences.get("minimum_salary", profile.get("minimum_salary"))
    max_age = float(prefs.get("job_age_limit_hours", profile.get("job_age_limit_hours", 24)))
    posted = job.get("posted_at")
    if isinstance(posted, str):
        try: posted = datetime.fromisoformat(posted.replace("Z", "+00:00"))
        except ValueError: posted = None
    if posted and posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    age_ok = posted is not None and (datetime.now(timezone.utc) - posted.astimezone(timezone.utc)).total_seconds() <= max_age * 3600
    salary_ok = min_salary is None or (job.get("salary_max") is not None and job["salary_max"] >= min_salary)
    if score < float(prefs.get("review_threshold", 70)):
        return {"decision": "SKIP", "reasons": ["Below minimum review score"]}
    if not salary_ok:
        return {"decision": "REVIEW_REQUIRED", "reasons": ["Salary is below minimum or undisclosed"]}
    if not age_ok:
        return {"decision": "REVIEW_REQUIRED", "reasons": ["Posting age is unknown or exceeds configured limit"]}
    locations = preferences.get("preferred_locations", [])
    job_location = job.get("location", "").casefold()
    if locations and not any(str(location).casefold() in job_location for location in locations) and not ("remote" in job_location and preferences.get("remote_allowed", False)):
        return {"decision": "REVIEW_REQUIRED", "reasons": ["Location does not match a configured preference"]}
    if not connector_supports_application:
        return {"decision": "MANUAL_ACTION_REQUIRED", "reasons": ["No permitted submission connector is configured"]}
    if mode != "AUTO_APPLY" or not prefs.get("auto_apply_enabled", False) or score < min_score:
        return {"decision": "REVIEW_REQUIRED", "reasons": ["User confirmation is required by current mode or score threshold"]}
    return {"decision": "ELIGIBLE", "reasons": ["All configured rules passed; submission still requires permitted connector and verified confirmation"]}
