import asyncio

from app.platforms.public_feeds import (
    FEED_CACHE_SECONDS,
    clear_public_feed_cache,
    fetch_public_feed,
    normalize_remotive,
    normalize_remoteok,
)


def test_public_feed_normalizers_keep_attributed_https_listing_urls():
    remoteok = normalize_remoteok({
        "id": 123,
        "slug": "data-analyst-123",
        "position": "Data Analyst",
        "company": "Example Co",
        "url": "https://remoteok.com/remote-jobs/data-analyst-123",
        "date": "2026-10-20T12:00:00+00:00",
        "tags": ["Excel", "SQL"],
        "description": "Analyze reports with Excel and SQL.",
    })
    assert remoteok is not None
    assert remoteok["platform"] == "remoteok"
    assert remoteok["application_url"] == "https://remoteok.com/remote-jobs/data-analyst-123"
    assert remoteok["remote_type"] == "REMOTE"
    assert remoteok["application_type"] == "MANUAL"

    remotive = normalize_remotive({
        "id": 456,
        "title": "Data Analyst",
        "company_name": "Example Co",
        "url": "https://remotive.com/remote-jobs/analytics/data-analyst-456",
        "candidate_required_location": "Worldwide",
        "publication_date": "2026-10-20T12:00:00",
        "job_type": "full_time",
        "category": "Data Analytics",
        "tags": ["Excel", "SQL"],
        "description": "Analyze reports with Excel and SQL.",
    })
    assert remotive is not None
    assert remotive["platform"] == "remotive"
    assert remotive["application_url"].startswith("https://remotive.com/remote-jobs/")
    assert remotive["employment_type"] == "FULL_TIME"
    assert remotive["application_type"] == "MANUAL"


def test_public_feed_normalizers_reject_untrusted_job_urls():
    remoteok = normalize_remoteok({"id": 1, "position": "Role", "company": "Example", "url": "https://evil.example/apply"})
    remotive = normalize_remotive({"id": 2, "title": "Role", "company_name": "Example", "url": "javascript:alert(1)"})
    assert remoteok is not None and remoteok["application_url"] == "https://remoteok.com/remote-jobs/1"
    assert remotive is not None and remotive["application_url"] == "https://remotive.com/remote-jobs/2"


def test_public_feed_normalizers_ignore_metadata_rows():
    assert normalize_remoteok({"legal": "Remote OK API legal notice"}) is None
    assert normalize_remotive({"id": 1, "title": "Missing company"}) is None


def test_public_feed_refresh_is_shared_and_remotive_is_daily():
    clear_public_feed_cache()
    calls = {"remoteok": 0, "remotive": 0}

    async def fetch_remoteok():
        calls["remoteok"] += 1
        return [{"id": "remoteok-job"}]

    async def fetch_remotive():
        calls["remotive"] += 1
        return [{"id": "remotive-job"}]

    async def run():
        first = await fetch_public_feed("remotive", remotive_fetcher=fetch_remotive)
        second = await fetch_public_feed("remotive", remotive_fetcher=fetch_remotive)
        await fetch_public_feed("remoteok", remoteok_fetcher=fetch_remoteok)
        await fetch_public_feed("remoteok", remoteok_fetcher=fetch_remoteok)
        assert first == second == [{"id": "remotive-job"}]

    asyncio.run(run())
    assert calls == {"remoteok": 1, "remotive": 1}
    assert FEED_CACHE_SECONDS["remotive"] == 24 * 60 * 60
    clear_public_feed_cache()
