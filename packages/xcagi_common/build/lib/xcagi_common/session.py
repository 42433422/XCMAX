"""Session id extraction shared by FastAPI apps."""

from __future__ import annotations


def session_id_from_authorization_header(
    authorization: str | None,
    *,
    bearer_prefix: str = "Bearer ",
) -> str | None:
    if not authorization:
        return None
    text = authorization.strip()
    if text.startswith(bearer_prefix):
        token = text[len(bearer_prefix) :].strip()
        return token or None
    return None
