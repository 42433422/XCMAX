"""Security subsystem health probe for ops dashboards."""
from __future__ import annotations

from typing import Any

from app.security import csrf_protect, input_sanitizer, secrets_redactor, threat_headers
from app.security.authz_policy import Principal, require_any_role
from app.security.rate_limit_policy import TokenBucket


def security_surface_report() -> dict[str, Any]:
    return {
        "modules": [
            "input_sanitizer",
            "secrets_redactor",
            "authz_policy",
            "csrf_protect",
            "rate_limit_policy",
            "threat_headers",
            "audit_trail",
            "session_hardening",
            "path_traversal_guard",
        ],
        "headers": list(threat_headers.SECURITY_HEADERS),
        "csrf_sample_ok": csrf_protect.verify_csrf(csrf_protect.mint_csrf("probe")),
        "sanitize_ok": input_sanitizer.sanitize_text("<script>x</script>hi") == "hi",
        "redact_ok": "[REDACTED]" in secrets_redactor.redact_text("api_key=abcd"),
        "bucket": TokenBucket(1.0, 2).allow(),
        "authz": require_any_role(Principal("u", frozenset({"admin"})), ["admin"]),
    }
