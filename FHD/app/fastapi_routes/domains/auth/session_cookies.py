"""The existing session cookie policy, shared by every login entry point."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from fastapi import Response


@dataclass(frozen=True)
class SessionCookies:
    environ: Mapping[str, str]

    def attach(self, response: Response, session_id: str | None) -> Response:
        sid = (session_id or "").strip()
        if not sid:
            return response
        raw_samesite = self.environ.get("SESSION_COOKIE_SAMESITE", "Lax").strip().lower()
        samesite = cast(
            Literal["lax", "strict", "none"],
            raw_samesite if raw_samesite in {"lax", "strict", "none"} else "lax",
        )
        response.set_cookie(
            key=self.environ.get("SESSION_COOKIE_NAME", "session_id"),
            value=sid,
            max_age=int(self.environ.get("SESSION_COOKIE_MAX_AGE", "315360000")),
            httponly=self.environ.get("SESSION_COOKIE_HTTPONLY", "1")
            not in ("0", "false", "False"),
            secure=self.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
            samesite=samesite,
            path="/",
        )
        return response

    def remove(self, response: Response) -> Response:
        response.delete_cookie(self.environ.get("SESSION_COOKIE_NAME", "session_id"), path="/")
        return response
