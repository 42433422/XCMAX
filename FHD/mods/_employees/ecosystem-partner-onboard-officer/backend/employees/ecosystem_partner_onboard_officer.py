"""Deterministic, read-only partner-onboarding readiness audit."""

from __future__ import annotations

from typing import Any

EMPLOYEE_ID = "ecosystem-partner-onboard-officer"
_REQUIRED = ("partner_id", "partner_name", "tenant_id", "sso_mode", "permissions", "first_goal")
_SENSITIVE = {"token", "secret", "password", "api_key", "access_token", "private_key"}


def _sensitive_paths(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key).strip()
            path = f"{prefix}.{name}".strip(".")
            if name.lower() in _SENSITIVE:
                found.append(path)
            found.extend(_sensitive_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value[:200]):
            found.extend(_sensitive_paths(item, f"{prefix}[{index}]"))
    return found[:100]


def _failure(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message[:500],
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Audit a supplied partner profile; never provisions tenants or SSO."""

    data = dict(payload or {})
    if str(data.get("action") or "audit_partner_readiness") != "audit_partner_readiness":
        return _failure("unsupported action", "unsupported_action")
    sensitive = _sensitive_paths(data)
    if sensitive:
        return _failure("输入包含禁止收集的密钥字段", "sensitive_input_blocked")
    profile = data.get("partner_profile")
    if not isinstance(profile, dict):
        return _failure("partner_profile object is required", "missing_partner_profile")

    missing = [field for field in _REQUIRED if profile.get(field) in (None, "", [], {})]
    permissions = profile.get("permissions") if isinstance(profile.get("permissions"), list) else []
    issues: list[dict[str, str]] = [
        {"code": "missing_field", "path": f"partner_profile.{field}"} for field in missing
    ]
    if profile.get("tenant_id") and not bool(profile.get("tenant_isolated")):
        issues.append(
            {"code": "tenant_isolation_unproven", "path": "partner_profile.tenant_isolated"}
        )
    if "admin" in {str(value).strip().lower() for value in permissions}:
        issues.append({"code": "overbroad_permission", "path": "partner_profile.permissions"})
    status = "approved" if not issues else "rejected"
    partner_id = str(profile.get("partner_id") or "?").strip()[:160]
    return {
        "ok": True,
        "status": status,
        "summary": (
            f"伙伴 {partner_id} 的接入资料已完成只读核对："
            f"{len(_REQUIRED) - len(missing)}/{len(_REQUIRED)} 个核心字段完整，"
            f"发现 {len(issues)} 个阻塞项；未创建租户或 SSO。"
        ),
        "partner_id": partner_id,
        "missing_fields": missing,
        "issues": issues,
        "ready_for_onboarding": not issues,
        "permission_count": len(permissions),
        "evidence": [f"input.partner_profile.{field}" for field in _REQUIRED],
        "read_only": True,
        "side_effects": [],
        "meta": {"employee_id": EMPLOYEE_ID, "contract_version": "1.0"},
    }
