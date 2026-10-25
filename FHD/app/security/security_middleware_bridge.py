"""Bridge helpers so middleware can depend on app.security instead of ad-hoc checks."""
from __future__ import annotations

from typing import Any, Callable

from app.security.security_controls import (
    IpAllowlist,
    RequestSecurityContext,
    build_default_buckets,
    evaluate_login_attempt,
    secure_response_envelope,
)
from app.security.threat_headers import apply_security_headers


class SecurityMiddlewareBridge:
    def __init__(self, allow_cidrs: list[str] | None = None) -> None:
        self.allowlist = IpAllowlist(allow_cidrs)
        self.buckets = build_default_buckets()

    def check_auth(self, ctx: RequestSecurityContext, roles: list[str] | None = None) -> tuple[bool, str]:
        return evaluate_login_attempt(
            principal=ctx.principal,
            client_ip=ctx.client_ip,
            allowlist=self.allowlist,
            bucket=self.buckets["auth"],
            required_roles=roles,
        )

    def wrap_payload(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        return secure_response_envelope(payload, apply_security_headers(headers or {}))
