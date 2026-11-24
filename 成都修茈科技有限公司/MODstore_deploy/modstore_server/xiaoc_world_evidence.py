"""Typed public-source observations for the existing XiaoC cognition graph."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ExternalObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source: Literal["configured_searxng"] = "configured_searxng"
    url: str = Field(min_length=1, max_length=1000)
    source_host: str
    title: str = Field(max_length=150)
    snippet: str = Field(max_length=700)
    engine: str | None = Field(default=None, max_length=100)
    publication_date_reported: str | None = Field(default=None, max_length=128)
    published_at: AwareDatetime | None = None
    collected_at: AwareDatetime
    observation_kind: Literal["retrieved_source"] = "retrieved_source"
    knowledge_kind: Literal["unknown"] = "unknown"
    claim_confidence: Literal["unverified"] = "unverified"
    probability: None = None


def public_source_observation(row: dict[str, Any], collected_at: datetime) -> dict[str, Any] | None:
    """Preserve reported provenance without promoting a search snippet to a fact."""
    url = str(row.get("url") or "")
    if not url or len(url) > 1000:
        return None
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        return None
    raw = row.get("publishedDate")
    reported = raw.strip()[:128] if isinstance(raw, str) and raw.strip() else None
    published = None
    if reported:
        try:
            published = datetime.fromisoformat(reported.replace("Z", "+00:00"))
        except ValueError:
            try:
                published = parsedate_to_datetime(reported)
            except (ValueError, TypeError, OverflowError):
                published = None
        # Date-only, unspecified timezones and future dates are not verified instants.
        if published is not None:
            if published.tzinfo is None:
                published = None
            else:
                try:
                    published = published.astimezone(UTC)
                except OverflowError:
                    published = None
            if published is not None and published > collected_at:
                published = None
    return ExternalObservation(
        url=url,
        source_host=host.lower(),
        title=str(row.get("title") or "")[:150],
        snippet=str(row.get("content") or "")[:700],
        engine=str(row["engine"])[:100] if row.get("engine") else None,
        publication_date_reported=reported,
        published_at=published,
        collected_at=collected_at,
    ).model_dump(mode="json")
