"""Read-only adapters for public Greenhouse and Lever career-board APIs.

These APIs expose published listings. Applications are always completed on the
employer's hosted page because submission access requires employer authorization.
"""

from datetime import datetime, timezone
from html.parser import HTMLParser
import re
from urllib.parse import quote, urlparse
from typing import Any

import httpx

from app.services.resume_parser import KNOWN_SKILLS


MAX_JOBS_PER_BOARD = 250
_SLUG = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


class _TextOnlyHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._hidden_depth += 1
        elif tag.lower() in {"p", "br", "li", "div", "section", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._hidden_depth:
            self._hidden_depth -= 1
        elif tag.lower() in {"p", "li", "div", "section", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def html_to_text(value: str | None) -> str:
    parser = _TextOnlyHTML()
    parser.feed(value or "")
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _date(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _skills(text: str) -> list[str]:
    lowered = text.casefold()
    return sorted(skill for skill in KNOWN_SKILLS if re.search(rf"(?<![\w+#.]){re.escape(skill)}(?![\w+#.])", lowered))


def _trusted_job_url(value: Any, *, host: str, fallback: str) -> str:
    """Accept only HTTPS job links on the platform's published-job host."""
    if isinstance(value, str):
        parsed = urlparse(value)
        if parsed.scheme == "https" and parsed.hostname == host and not parsed.username and not parsed.password:
            return value
    return fallback


def normalize_greenhouse(raw: dict[str, Any], *, board_token: str, company_name: str) -> dict[str, Any]:
    location = (raw.get("location") or {}).get("name", "")
    description = html_to_text(raw.get("content"))
    job_id = str(raw.get("id", ""))
    fallback_url = f"https://boards.greenhouse.io/{quote(board_token, safe='')}/jobs/{quote(job_id, safe='')}"
    url = _trusted_job_url(raw.get("absolute_url"), host="boards.greenhouse.io", fallback=fallback_url)
    return {
        "platform": "greenhouse",
        "platform_job_id": f"{board_token}:{job_id}",
        "title": str(raw.get("title") or "Untitled role")[:300],
        "company": company_name or board_token,
        "location": str(location)[:300],
        "remote_type": "UNKNOWN",
        "salary_min": None,
        "salary_max": None,
        "currency": None,
        "experience_min": None,
        "experience_max": None,
        "skills": _skills(description),
        "description": description[:30000],
        "requirements": [],
        "benefits": [],
        "employment_type": "UNKNOWN",
        "posted_at": _date(raw.get("updated_at")),
        "application_url": url,
        "application_type": "MANUAL",
        "recruiter": None,
        "source_url": url,
    }


def normalize_lever(raw: dict[str, Any], *, board_token: str, company_name: str) -> dict[str, Any]:
    categories = raw.get("categories") or {}
    location = categories.get("location") or ", ".join(categories.get("allLocations") or [])
    description = str(raw.get("descriptionPlain") or html_to_text(raw.get("description")))
    salary = raw.get("salaryRange") or {}
    workplace = str(raw.get("workplaceType") or "").casefold()
    remote_type = {"remote": "REMOTE", "hybrid": "HYBRID", "on-site": "ONSITE"}.get(workplace, "UNKNOWN")
    fallback_url = f"https://jobs.lever.co/{quote(board_token, safe='')}/{quote(str(raw.get('id', '')), safe='')}"
    url = _trusted_job_url(raw.get("hostedUrl"), host="jobs.lever.co", fallback=fallback_url)
    commitment = str(categories.get("commitment") or "").casefold()
    employment_type = "INTERNSHIP" if "intern" in commitment else "CONTRACT" if "contract" in commitment else "FULL_TIME" if "full" in commitment else "UNKNOWN"
    return {
        "platform": "lever",
        "platform_job_id": f"{board_token}:{raw.get('id', '')}",
        "title": str(raw.get("text") or "Untitled role")[:300],
        "company": company_name or board_token,
        "location": str(location)[:300],
        "remote_type": remote_type,
        "salary_min": salary.get("min"),
        "salary_max": salary.get("max"),
        "currency": salary.get("currency"),
        "experience_min": None,
        "experience_max": None,
        "skills": _skills(description),
        "description": description[:30000],
        "requirements": [],
        "benefits": [],
        "employment_type": employment_type,
        "posted_at": _date(raw.get("createdAt")),
        "application_url": url,
        "application_type": "MANUAL",
        "recruiter": None,
        "source_url": url,
    }


def validate_board(provider: str, board_token: str) -> tuple[str, str]:
    provider = provider.casefold().strip()
    board_token = board_token.strip()
    if provider not in {"greenhouse", "lever"}:
        raise ValueError("Company career discovery supports Greenhouse and Lever boards only")
    if not _SLUG.fullmatch(board_token):
        raise ValueError("Board token must contain only letters, numbers, underscores, or hyphens")
    return provider, board_token


async def fetch_board(provider: str, board_token: str, company_name: str, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    provider, board_token = validate_board(provider, board_token)
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5), follow_redirects=False)
    try:
        slug = quote(board_token, safe="")
        if provider == "greenhouse":
            response = await http.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("jobs", []) if isinstance(payload, dict) else []
            normalize = normalize_greenhouse
        else:
            response = await http.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json", "limit": MAX_JOBS_PER_BOARD})
            response.raise_for_status()
            payload = response.json()
            rows = payload if isinstance(payload, list) else []
            normalize = normalize_lever
        return [normalize(row, board_token=board_token, company_name=company_name) for row in rows[:MAX_JOBS_PER_BOARD] if isinstance(row, dict) and row.get("id") is not None]
    finally:
        if owns_client:
            await http.aclose()
