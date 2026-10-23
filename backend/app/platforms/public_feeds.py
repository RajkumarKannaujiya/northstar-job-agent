"""Read-only adapters for public job feeds that allow candidate-facing aggregation.

Listings stay attributed to their source and always open on the original job page.
This module never submits applications or sends resume data to the feed providers.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.platforms.career_pages import _date, _skills, html_to_text


FEED_TIMEOUT = httpx.Timeout(15, connect=5)
FEED_LIMIT = 100
FEED_CACHE_SECONDS = {"remoteok": 6 * 60 * 60, "remotive": 24 * 60 * 60}
_feed_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_feed_locks = {provider: asyncio.Lock() for provider in FEED_CACHE_SECONDS}


def _trusted_listing_url(value: Any, *, host: str, fallback: str) -> str:
    if isinstance(value, str):
        parsed = urlparse(value)
        if parsed.scheme == "https" and parsed.hostname in {host, f"www.{host}"} and not parsed.username and not parsed.password:
            return value
    return fallback


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def normalize_remoteok(raw: dict[str, Any]) -> dict[str, Any] | None:
    job_id = str(raw.get("id") or raw.get("slug") or "").strip()
    title = str(raw.get("position") or "").strip()
    company = str(raw.get("company") or "").strip()
    if not job_id or not title or not company:
        return None
    fallback = f"https://remoteok.com/remote-jobs/{job_id}"
    url = _trusted_listing_url(raw.get("url"), host="remoteok.com", fallback=fallback)
    description = html_to_text(str(raw.get("description") or ""))
    posted_at = _date(raw.get("date"))
    if posted_at is None and isinstance(raw.get("epoch"), (int, float)):
        try:
            posted_at = datetime.fromtimestamp(raw["epoch"], tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            posted_at = None
    tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    skills = sorted({str(tag).strip()[:120] for tag in tags if isinstance(tag, str) and tag.strip()})
    skills = skills or _skills(f"{title} {description}")
    return {
        "platform": "remoteok",
        "platform_job_id": job_id,
        "title": title[:300],
        "company": company[:300],
        "location": str(raw.get("location") or "Remote").strip()[:300],
        "remote_type": "REMOTE",
        "salary_min": _number(raw.get("salary_min")),
        "salary_max": _number(raw.get("salary_max")),
        "currency": None,
        "experience_min": None,
        "experience_max": None,
        "skills": skills[:80],
        "description": description[:30000],
        "requirements": [],
        "benefits": [],
        "employment_type": "UNKNOWN",
        "posted_at": posted_at,
        "application_url": url,
        "application_type": "MANUAL",
        "recruiter": None,
        "source_url": url,
    }


def normalize_remotive(raw: dict[str, Any]) -> dict[str, Any] | None:
    job_id = str(raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()
    company = str(raw.get("company_name") or "").strip()
    if not job_id or not title or not company:
        return None
    fallback = f"https://remotive.com/remote-jobs/{job_id}"
    url = _trusted_listing_url(raw.get("url"), host="remotive.com", fallback=fallback)
    description = html_to_text(str(raw.get("description") or ""))
    tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    category = str(raw.get("category") or "").strip()
    skills = sorted({str(tag).strip()[:120] for tag in tags if isinstance(tag, str) and tag.strip()})
    if category:
        skills.append(category[:120])
    skills = skills or _skills(f"{title} {description}")
    job_type = str(raw.get("job_type") or "").casefold()
    employment = {
        "full_time": "FULL_TIME",
        "part_time": "PART_TIME",
        "contract": "CONTRACT",
        "freelance": "CONTRACT",
        "internship": "INTERNSHIP",
    }.get(job_type, "UNKNOWN")
    location = str(raw.get("candidate_required_location") or "Worldwide").strip()
    return {
        "platform": "remotive",
        "platform_job_id": job_id,
        "title": title[:300],
        "company": company[:300],
        "location": location[:300],
        "remote_type": "REMOTE",
        "salary_min": None,
        "salary_max": None,
        "currency": None,
        "experience_min": None,
        "experience_max": None,
        "skills": skills[:80],
        "description": description[:30000],
        "requirements": [],
        "benefits": [],
        "employment_type": employment,
        "posted_at": _date(raw.get("publication_date")),
        "application_url": url,
        "application_type": "MANUAL",
        "recruiter": None,
        "source_url": url,
    }


async def fetch_remoteok(client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=FEED_TIMEOUT, follow_redirects=False, headers={"User-Agent": "NorthstarJobAgent/1.0"})
    try:
        response = await http.get("https://remoteok.com/api")
        response.raise_for_status()
        payload = response.json()
        rows = payload if isinstance(payload, list) else []
        return [job for row in rows if isinstance(row, dict) if (job := normalize_remoteok(row)) is not None][:FEED_LIMIT]
    finally:
        if owns_client:
            await http.aclose()


async def fetch_remotive(search_term: str | None = None, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=FEED_TIMEOUT, follow_redirects=False, headers={"User-Agent": "NorthstarJobAgent/1.0"})
    try:
        params: dict[str, Any] = {"limit": FEED_LIMIT}
        if search_term:
            params["search"] = search_term[:100]
        response = await http.get("https://remotive.com/api/remote-jobs", params=params)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("jobs", []) if isinstance(payload, dict) else []
        return [job for row in rows if isinstance(row, dict) if (job := normalize_remotive(row)) is not None][:FEED_LIMIT]
    finally:
        if owns_client:
            await http.aclose()


async def fetch_public_feed(
    provider: str,
    *,
    remoteok_fetcher=fetch_remoteok,
    remotive_fetcher=fetch_remotive,
) -> list[dict[str, Any]]:
    """Share feed refreshes across accounts and observe provider-specific cadence."""
    if provider not in FEED_CACHE_SECONDS:
        raise ValueError("Unsupported public job feed")
    now = time.monotonic()
    cached = _feed_cache.get(provider)
    if cached and now - cached[0] < FEED_CACHE_SECONDS[provider]:
        return cached[1]
    async with _feed_locks[provider]:
        now = time.monotonic()
        cached = _feed_cache.get(provider)
        if cached and now - cached[0] < FEED_CACHE_SECONDS[provider]:
            return cached[1]
        rows = await (remoteok_fetcher() if provider == "remoteok" else remotive_fetcher())
        _feed_cache[provider] = (time.monotonic(), rows)
        return rows


def clear_public_feed_cache() -> None:
    """Reset process cache for deterministic tests and local maintenance."""
    _feed_cache.clear()
