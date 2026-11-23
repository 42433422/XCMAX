"""External retrieval metadata is not evidence that a claim is true."""

from datetime import UTC, datetime

from modstore_server.xiaoc_world_evidence import public_source_observation

NOW = datetime(2026, 11, 24, 0, 0, tzinfo=UTC)


def test_source_observation_keeps_provenance_and_uncertainty():
    result = public_source_observation(
        {
            "url": "https://example.org/report",
            "title": "A market claim",
            "content": "Reported claim",
            "engine": "example",
            "publishedDate": "2026-11-22T12:00:00Z",
        },
        NOW,
    )
    assert result is not None
    assert result["source_host"] == "example.org"
    assert result["published_at"] == "2026-11-22T12:00:00Z"
    assert result["collected_at"] == "2026-11-24T00:00:00Z"
    assert result["knowledge_kind"] == "unknown"
    assert result["claim_confidence"] == "unverified"
    assert result["probability"] is None


def test_unknown_or_future_publication_is_not_invented():
    for date in (None, "not-a-date", "2026-11-20", "2027-01-01T00:00:00Z"):
        result = public_source_observation(
            {"url": "https://example.org/report", "publishedDate": date}, NOW
        )
        assert result is not None
        assert result["publication_date_reported"] == date
        assert result["published_at"] is None


def test_invalid_public_url_cannot_become_evidence():
    for url in ("file:///tmp/secret", "https://user:pw@example.org", "https://["):
        assert public_source_observation({"url": url}, NOW) is None
