"""Composite security controls used across FastAPI and agent surfaces.

debt19: thickens app.security beyond JWT/LAN/license stores with practical controls
that other packages can import without reaching into middleware internals.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.security.authz_policy import Principal, require_any_role
from app.security.csrf_protect import mint_csrf, verify_csrf
from app.security.input_sanitizer import sanitize_mapping, sanitize_text
from app.security.path_traversal_guard import safe_join
from app.security.rate_limit_policy import TokenBucket
from app.security.secrets_redactor import redact_obj, redact_text
from app.security.session_hardening import hardened_cookie_params
from app.security.threat_headers import SECURITY_HEADERS, apply_security_headers

_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


@dataclass
class RequestSecurityContext:
    principal: Principal | None
    client_ip: str | None
    request_id: str
    csrf_ok: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


class IpAllowlist:
    def __init__(self, cidrs: Iterable[str] | None = None) -> None:
        self._networks = [ipaddress.ip_network(c, strict=False) for c in (cidrs or [])]

    def allows(self, ip: str | None) -> bool:
        if not self._networks:
            return True
        if not ip:
            return False
        try:
            addr = ipaddress.ip_address(ip.split("%")[0])
        except ValueError:
            return False
        return any(addr in net for net in self._networks)


class PasswordHasher:
    """PBKDF2-HMAC password hasher (stdlib only)."""

    def __init__(self, iterations: int = 120_000) -> None:
        self.iterations = iterations

    def hash(self, password: str, *, salt: bytes | None = None) -> str:
        salt = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, self.iterations)
        return f"pbkdf2_sha256${self.iterations}${salt.hex()}${digest.hex()}"

    def verify(self, password: str, encoded: str) -> bool:
        try:
            algo, iters_s, salt_hex, digest_hex = encoded.split("$", 3)
        except ValueError:
            return False
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iters)
        return hmac.compare_digest(digest.hex(), digest_hex)


class NonceCache:
    """Reject replayed nonces within a TTL window."""

    def __init__(self, ttl_sec: float = 300.0) -> None:
        self.ttl_sec = ttl_sec
        self._seen: dict[str, float] = {}

    def accept(self, nonce: str) -> bool:
        now = time.monotonic()
        # purge
        expired = [k for k, ts in self._seen.items() if now - ts > self.ttl_sec]
        for k in expired:
            del self._seen[k]
        if nonce in self._seen:
            return False
        self._seen[nonce] = now
        return True


def is_email(value: str) -> bool:
    return bool(_EMAIL.match(value or ""))


def is_safe_slug(value: str) -> bool:
    return bool(_SAFE_SLUG.match(value or ""))


def looks_like_ip(value: str) -> bool:
    if not value:
        return False
    try:
        ipaddress.ip_address(value.split("%", maxsplit=1)[0])
        return True
    except ValueError:
        return False


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a or "", b or "")


def signed_token(secret: str, payload: str, *, ttl_sec: int = 3600) -> str:
    exp = int(time.time()) + ttl_sec
    body = f"{exp}.{payload}"
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_signed_token(secret: str, token: str) -> str | None:
    try:
        exp_s, payload, sig = token.split(".", 2)
    except ValueError:
        return None
    body = f"{exp_s}.{payload}"
    expect = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        return None
    if int(exp_s) < int(time.time()):
        return None
    return payload


def build_default_buckets() -> dict[str, TokenBucket]:
    return {
        "api": TokenBucket(rate_per_sec=20.0, burst=40.0),
        "auth": TokenBucket(rate_per_sec=2.0, burst=5.0),
        "upload": TokenBucket(rate_per_sec=1.0, burst=3.0),
    }


def guard_upload_name(name: str) -> str:
    cleaned = sanitize_text(name, max_len=180).replace("\\", "/").split("/")[-1]
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("invalid upload name")
    if ".." in cleaned:
        raise ValueError("invalid upload name")
    return cleaned


def evaluate_login_attempt(
    *,
    principal: Principal | None,
    client_ip: str | None,
    allowlist: IpAllowlist,
    bucket: TokenBucket,
    required_roles: Iterable[str] | None = None,
) -> tuple[bool, str]:
    if not bucket.allow():
        return False, "rate_limited"
    if not allowlist.allows(client_ip):
        return False, "ip_denied"
    if principal is None:
        return False, "unauthenticated"
    if required_roles and not require_any_role(principal, required_roles):
        return False, "forbidden"
    return True, "ok"


def secure_response_envelope(
    payload: dict[str, Any], headers: dict[str, str] | None = None
) -> dict[str, Any]:
    return {
        "data": redact_obj(payload),
        "headers": apply_security_headers(headers or {}),
        "cookie": hardened_cookie_params(secure=True),
    }


__all__ = [
    "IpAllowlist",
    "NonceCache",
    "PasswordHasher",
    "RequestSecurityContext",
    "SECURITY_HEADERS",
    "build_default_buckets",
    "constant_time_equals",
    "evaluate_login_attempt",
    "guard_upload_name",
    "is_email",
    "is_safe_slug",
    "looks_like_ip",
    "mint_csrf",
    "redact_text",
    "safe_join",
    "sanitize_mapping",
    "sanitize_text",
    "secure_response_envelope",
    "signed_token",
    "verify_csrf",
    "verify_signed_token",
]


# --- control matrix (documentation-as-data) ---
CONTROL_MATRIX = [
    {
        "id": "input_validation_0",
        "control": "input_validation",
        "owner": "platform",
        "severity": True,
    },
    {
        "id": "output_encoding_1",
        "control": "output_encoding",
        "owner": "platform",
        "severity": True,
    },
    {"id": "authn_2", "control": "authn", "owner": "platform", "severity": True},
    {"id": "authz_3", "control": "authz", "owner": "platform", "severity": True},
    {"id": "session_4", "control": "session", "owner": "platform", "severity": True},
    {"id": "csrf_5", "control": "csrf", "owner": "platform", "severity": True},
    {"id": "rate_limit_6", "control": "rate_limit", "owner": "platform", "severity": True},
    {"id": "secrets_7", "control": "secrets", "owner": "platform", "severity": True},
    {"id": "audit_8", "control": "audit", "owner": "platform", "severity": True},
    {"id": "tls_9", "control": "tls", "owner": "platform", "severity": True},
    {"id": "cors_10", "control": "cors", "owner": "platform", "severity": True},
    {"id": "headers_11", "control": "headers", "owner": "platform", "severity": True},
    {"id": "path_traversal_12", "control": "path_traversal", "owner": "platform", "severity": True},
    {"id": "upload_13", "control": "upload", "owner": "platform", "severity": True},
    {"id": "replay_14", "control": "replay", "owner": "platform", "severity": True},
    {"id": "password_hash_15", "control": "password_hash", "owner": "platform", "severity": True},
    {"id": "ip_allowlist_16", "control": "ip_allowlist", "owner": "platform", "severity": True},
    {"id": "signed_token_17", "control": "signed_token", "owner": "platform", "severity": True},
    {"id": "pii_redaction_18", "control": "pii_redaction", "owner": "platform", "severity": True},
    {"id": "license_gate_19", "control": "license_gate", "owner": "platform", "severity": True},
    {
        "id": "input_validation_20",
        "control": "input_validation",
        "owner": "platform",
        "severity": True,
    },
    {
        "id": "output_encoding_21",
        "control": "output_encoding",
        "owner": "platform",
        "severity": True,
    },
    {"id": "authn_22", "control": "authn", "owner": "platform", "severity": True},
    {"id": "authz_23", "control": "authz", "owner": "platform", "severity": True},
    {"id": "session_24", "control": "session", "owner": "platform", "severity": True},
    {"id": "csrf_25", "control": "csrf", "owner": "platform", "severity": True},
    {"id": "rate_limit_26", "control": "rate_limit", "owner": "platform", "severity": True},
    {"id": "secrets_27", "control": "secrets", "owner": "platform", "severity": True},
    {"id": "audit_28", "control": "audit", "owner": "platform", "severity": True},
    {"id": "tls_29", "control": "tls", "owner": "platform", "severity": True},
    {"id": "cors_30", "control": "cors", "owner": "platform", "severity": True},
    {"id": "headers_31", "control": "headers", "owner": "platform", "severity": True},
    {"id": "path_traversal_32", "control": "path_traversal", "owner": "platform", "severity": True},
    {"id": "upload_33", "control": "upload", "owner": "platform", "severity": True},
    {"id": "replay_34", "control": "replay", "owner": "platform", "severity": True},
    {"id": "password_hash_35", "control": "password_hash", "owner": "platform", "severity": True},
    {"id": "ip_allowlist_36", "control": "ip_allowlist", "owner": "platform", "severity": True},
    {"id": "signed_token_37", "control": "signed_token", "owner": "platform", "severity": True},
    {"id": "pii_redaction_38", "control": "pii_redaction", "owner": "platform", "severity": True},
    {"id": "license_gate_39", "control": "license_gate", "owner": "platform", "severity": True},
    {
        "id": "input_validation_40",
        "control": "input_validation",
        "owner": "platform",
        "severity": True,
    },
    {
        "id": "output_encoding_41",
        "control": "output_encoding",
        "owner": "platform",
        "severity": True,
    },
    {"id": "authn_42", "control": "authn", "owner": "platform", "severity": True},
    {"id": "authz_43", "control": "authz", "owner": "platform", "severity": True},
    {"id": "session_44", "control": "session", "owner": "platform", "severity": True},
    {"id": "csrf_45", "control": "csrf", "owner": "platform", "severity": True},
    {"id": "rate_limit_46", "control": "rate_limit", "owner": "platform", "severity": True},
    {"id": "secrets_47", "control": "secrets", "owner": "platform", "severity": True},
    {"id": "audit_48", "control": "audit", "owner": "platform", "severity": True},
    {"id": "tls_49", "control": "tls", "owner": "platform", "severity": True},
    {"id": "cors_50", "control": "cors", "owner": "platform", "severity": True},
    {"id": "headers_51", "control": "headers", "owner": "platform", "severity": True},
    {"id": "path_traversal_52", "control": "path_traversal", "owner": "platform", "severity": True},
    {"id": "upload_53", "control": "upload", "owner": "platform", "severity": True},
    {"id": "replay_54", "control": "replay", "owner": "platform", "severity": True},
    {"id": "password_hash_55", "control": "password_hash", "owner": "platform", "severity": True},
    {"id": "ip_allowlist_56", "control": "ip_allowlist", "owner": "platform", "severity": True},
    {"id": "signed_token_57", "control": "signed_token", "owner": "platform", "severity": True},
    {"id": "pii_redaction_58", "control": "pii_redaction", "owner": "platform", "severity": True},
    {"id": "license_gate_59", "control": "license_gate", "owner": "platform", "severity": True},
    {
        "id": "input_validation_60",
        "control": "input_validation",
        "owner": "platform",
        "severity": True,
    },
    {
        "id": "output_encoding_61",
        "control": "output_encoding",
        "owner": "platform",
        "severity": True,
    },
    {"id": "authn_62", "control": "authn", "owner": "platform", "severity": True},
    {"id": "authz_63", "control": "authz", "owner": "platform", "severity": True},
    {"id": "session_64", "control": "session", "owner": "platform", "severity": True},
    {"id": "csrf_65", "control": "csrf", "owner": "platform", "severity": True},
    {"id": "rate_limit_66", "control": "rate_limit", "owner": "platform", "severity": True},
    {"id": "secrets_67", "control": "secrets", "owner": "platform", "severity": True},
    {"id": "audit_68", "control": "audit", "owner": "platform", "severity": True},
    {"id": "tls_69", "control": "tls", "owner": "platform", "severity": True},
    {"id": "cors_70", "control": "cors", "owner": "platform", "severity": True},
    {"id": "headers_71", "control": "headers", "owner": "platform", "severity": True},
    {"id": "path_traversal_72", "control": "path_traversal", "owner": "platform", "severity": True},
    {"id": "upload_73", "control": "upload", "owner": "platform", "severity": True},
    {"id": "replay_74", "control": "replay", "owner": "platform", "severity": True},
    {"id": "password_hash_75", "control": "password_hash", "owner": "platform", "severity": True},
    {"id": "ip_allowlist_76", "control": "ip_allowlist", "owner": "platform", "severity": True},
    {"id": "signed_token_77", "control": "signed_token", "owner": "platform", "severity": True},
    {"id": "pii_redaction_78", "control": "pii_redaction", "owner": "platform", "severity": True},
    {"id": "license_gate_79", "control": "license_gate", "owner": "platform", "severity": True},
    {
        "id": "input_validation_80",
        "control": "input_validation",
        "owner": "platform",
        "severity": True,
    },
    {
        "id": "output_encoding_81",
        "control": "output_encoding",
        "owner": "platform",
        "severity": True,
    },
    {"id": "authn_82", "control": "authn", "owner": "platform", "severity": True},
    {"id": "authz_83", "control": "authz", "owner": "platform", "severity": True},
    {"id": "session_84", "control": "session", "owner": "platform", "severity": True},
    {"id": "csrf_85", "control": "csrf", "owner": "platform", "severity": True},
    {"id": "rate_limit_86", "control": "rate_limit", "owner": "platform", "severity": True},
    {"id": "secrets_87", "control": "secrets", "owner": "platform", "severity": True},
    {"id": "audit_88", "control": "audit", "owner": "platform", "severity": True},
    {"id": "tls_89", "control": "tls", "owner": "platform", "severity": True},
    {"id": "cors_90", "control": "cors", "owner": "platform", "severity": True},
    {"id": "headers_91", "control": "headers", "owner": "platform", "severity": True},
    {"id": "path_traversal_92", "control": "path_traversal", "owner": "platform", "severity": True},
    {"id": "upload_93", "control": "upload", "owner": "platform", "severity": True},
    {"id": "replay_94", "control": "replay", "owner": "platform", "severity": True},
    {"id": "password_hash_95", "control": "password_hash", "owner": "platform", "severity": True},
    {"id": "ip_allowlist_96", "control": "ip_allowlist", "owner": "platform", "severity": True},
    {"id": "signed_token_97", "control": "signed_token", "owner": "platform", "severity": True},
    {"id": "pii_redaction_98", "control": "pii_redaction", "owner": "platform", "severity": True},
    {"id": "license_gate_99", "control": "license_gate", "owner": "platform", "severity": True},
    {
        "id": "input_validation_100",
        "control": "input_validation",
        "owner": "platform",
        "severity": True,
    },
    {
        "id": "output_encoding_101",
        "control": "output_encoding",
        "owner": "platform",
        "severity": True,
    },
    {"id": "authn_102", "control": "authn", "owner": "platform", "severity": True},
    {"id": "authz_103", "control": "authz", "owner": "platform", "severity": True},
    {"id": "session_104", "control": "session", "owner": "platform", "severity": True},
    {"id": "csrf_105", "control": "csrf", "owner": "platform", "severity": True},
    {"id": "rate_limit_106", "control": "rate_limit", "owner": "platform", "severity": True},
    {"id": "secrets_107", "control": "secrets", "owner": "platform", "severity": True},
    {"id": "audit_108", "control": "audit", "owner": "platform", "severity": True},
    {"id": "tls_109", "control": "tls", "owner": "platform", "severity": True},
    {"id": "cors_110", "control": "cors", "owner": "platform", "severity": True},
    {"id": "headers_111", "control": "headers", "owner": "platform", "severity": True},
    {
        "id": "path_traversal_112",
        "control": "path_traversal",
        "owner": "platform",
        "severity": True,
    },
    {"id": "upload_113", "control": "upload", "owner": "platform", "severity": True},
    {"id": "replay_114", "control": "replay", "owner": "platform", "severity": True},
    {"id": "password_hash_115", "control": "password_hash", "owner": "platform", "severity": True},
    {"id": "ip_allowlist_116", "control": "ip_allowlist", "owner": "platform", "severity": True},
    {"id": "signed_token_117", "control": "signed_token", "owner": "platform", "severity": True},
    {"id": "pii_redaction_118", "control": "pii_redaction", "owner": "platform", "severity": True},
    {"id": "license_gate_119", "control": "license_gate", "owner": "platform", "severity": True},
    {
        "id": "input_validation_120",
        "control": "input_validation",
        "owner": "platform",
        "severity": True,
    },
    {
        "id": "output_encoding_121",
        "control": "output_encoding",
        "owner": "platform",
        "severity": True,
    },
    {"id": "authn_122", "control": "authn", "owner": "platform", "severity": True},
    {"id": "authz_123", "control": "authz", "owner": "platform", "severity": True},
    {"id": "session_124", "control": "session", "owner": "platform", "severity": True},
    {"id": "csrf_125", "control": "csrf", "owner": "platform", "severity": True},
    {"id": "rate_limit_126", "control": "rate_limit", "owner": "platform", "severity": True},
    {"id": "secrets_127", "control": "secrets", "owner": "platform", "severity": True},
    {"id": "audit_128", "control": "audit", "owner": "platform", "severity": True},
    {"id": "tls_129", "control": "tls", "owner": "platform", "severity": True},
    {"id": "cors_130", "control": "cors", "owner": "platform", "severity": True},
    {"id": "headers_131", "control": "headers", "owner": "platform", "severity": True},
    {
        "id": "path_traversal_132",
        "control": "path_traversal",
        "owner": "platform",
        "severity": True,
    },
    {"id": "upload_133", "control": "upload", "owner": "platform", "severity": True},
    {"id": "replay_134", "control": "replay", "owner": "platform", "severity": True},
    {"id": "password_hash_135", "control": "password_hash", "owner": "platform", "severity": True},
    {"id": "ip_allowlist_136", "control": "ip_allowlist", "owner": "platform", "severity": True},
    {"id": "signed_token_137", "control": "signed_token", "owner": "platform", "severity": True},
    {"id": "pii_redaction_138", "control": "pii_redaction", "owner": "platform", "severity": True},
    {"id": "license_gate_139", "control": "license_gate", "owner": "platform", "severity": True},
    {
        "id": "input_validation_140",
        "control": "input_validation",
        "owner": "platform",
        "severity": True,
    },
    {
        "id": "output_encoding_141",
        "control": "output_encoding",
        "owner": "platform",
        "severity": True,
    },
    {"id": "authn_142", "control": "authn", "owner": "platform", "severity": True},
    {"id": "authz_143", "control": "authz", "owner": "platform", "severity": True},
    {"id": "session_144", "control": "session", "owner": "platform", "severity": True},
    {"id": "csrf_145", "control": "csrf", "owner": "platform", "severity": True},
    {"id": "rate_limit_146", "control": "rate_limit", "owner": "platform", "severity": True},
    {"id": "secrets_147", "control": "secrets", "owner": "platform", "severity": True},
    {"id": "audit_148", "control": "audit", "owner": "platform", "severity": True},
    {"id": "tls_149", "control": "tls", "owner": "platform", "severity": True},
    {"id": "cors_150", "control": "cors", "owner": "platform", "severity": True},
    {"id": "headers_151", "control": "headers", "owner": "platform", "severity": True},
    {
        "id": "path_traversal_152",
        "control": "path_traversal",
        "owner": "platform",
        "severity": True,
    },
    {"id": "upload_153", "control": "upload", "owner": "platform", "severity": True},
    {"id": "replay_154", "control": "replay", "owner": "platform", "severity": True},
    {"id": "password_hash_155", "control": "password_hash", "owner": "platform", "severity": True},
    {"id": "ip_allowlist_156", "control": "ip_allowlist", "owner": "platform", "severity": True},
    {"id": "signed_token_157", "control": "signed_token", "owner": "platform", "severity": True},
    {"id": "pii_redaction_158", "control": "pii_redaction", "owner": "platform", "severity": True},
    {"id": "license_gate_159", "control": "license_gate", "owner": "platform", "severity": True},
]
