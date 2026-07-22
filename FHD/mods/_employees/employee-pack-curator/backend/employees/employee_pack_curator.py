"""Deterministic, read-only employee-pack contract auditor."""

from __future__ import annotations

import re
from typing import Any, Dict

EMPLOYEE_ID = "employee-pack-curator"
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")
_SUPPORTED_HANDLERS = {
    "agent",
    "direct_python",
    "llm_md",
    "echo",
    "http_request",
    "webhook",
    "data_sync",
    "wechat_notify",
    "openapi_tool",
    "fhd_business",
    "voice_output",
    "para_delegate",
    "cursor_delegate",
    "vibe_edit",
    "vibe_heal",
    "vibe_code",
    "doc_sync",
    "shell_exec",
    "ssh_exec",
    "specialized",
}
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "private_key",
}


def _text(value: Any, *, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _failure(message: str, code: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message[:500],
        "error": message[:1000],
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }


def _sensitive_paths(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key or "").strip()
            path = f"{prefix}.{name}".strip(".")
            if name.lower() in _SENSITIVE_KEYS:
                found.append(path)
            found.extend(_sensitive_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value[:200]):
            found.extend(_sensitive_paths(item, f"{prefix}[{index}]"))
    return found[:100]


def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Audit a supplied manifest and optional registry record without mutation."""

    data = dict(payload or {})
    action = _text(data.get("action") or "audit_manifest", limit=80)
    if action != "audit_manifest":
        return _failure(f"unsupported action: {action}", "unsupported_action")
    manifest = data.get("manifest")
    if not isinstance(manifest, dict):
        return _failure("manifest object is required", "missing_manifest")

    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def issue(code: str, path: str, message: str) -> None:
        issues.append({"code": code, "path": path, "message": message})

    pack_id = _text(manifest.get("id"), limit=160)
    version = _text(manifest.get("version"), limit=80)
    artifact = _text(manifest.get("artifact"), limit=40)
    employee = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    employee_id = _text(employee.get("id"), limit=160)
    if not pack_id:
        issue("missing_id", "id", "manifest.id 必填")
    if not version:
        issue("missing_version", "version", "manifest.version 必填")
    elif not _SEMVER.fullmatch(version):
        issue("invalid_semver", "version", "version 必须是语义化版本")
    if artifact != "employee_pack":
        issue("invalid_artifact", "artifact", "artifact 必须为 employee_pack")
    if not employee:
        issue("missing_employee", "employee", "employee 对象必填")
    elif pack_id and employee_id != pack_id:
        issue("employee_id_mismatch", "employee.id", "employee.id 必须与 manifest.id 一致")

    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {}
    handlers = actions.get("handlers") if isinstance(actions.get("handlers"), list) else []
    clean_handlers = [_text(handler, limit=80) for handler in handlers if _text(handler, limit=80)]
    if not clean_handlers:
        issue("missing_handlers", "employee_config_v2.actions.handlers", "至少声明一个 handler")
    unknown = sorted(set(clean_handlers) - _SUPPORTED_HANDLERS)
    if unknown:
        issue(
            "unsupported_handlers",
            "employee_config_v2.actions.handlers",
            "运行时不支持: " + ", ".join(unknown),
        )
    if clean_handlers == ["echo"]:
        warnings.append(
            {
                "code": "echo_only_shell",
                "path": "employee_config_v2.actions.handlers",
                "message": "echo-only 不构成岗位真实执行能力",
            }
        )

    prompt = _text(
        ((v2.get("cognition") or {}).get("agent") or {}).get("system_prompt"),
        limit=20_000,
    )
    if len(prompt) < 50:
        issue(
            "system_prompt_too_short",
            "employee_config_v2.cognition.agent.system_prompt",
            "system_prompt 少于 50 字",
        )
    sensitive_paths = _sensitive_paths(manifest)
    if sensitive_paths:
        issue(
            "sensitive_fields_present",
            sensitive_paths[0],
            "manifest 包含敏感字段名，禁止进入员工包",
        )

    registry = data.get("registry_record")
    registry_consistent: bool | None = None
    if isinstance(registry, dict):
        registry_consistent = (
            _text(registry.get("id"), limit=160) == pack_id
            and _text(registry.get("version"), limit=80) == version
        )
        if not registry_consistent:
            issue("registry_mismatch", "registry_record", "registry id/version 与 manifest 不一致")

    status = "approved" if not issues else "rejected"
    summary = (
        f"员工包 {pack_id or '?'}@{version or '?'} 完成只读契约审计："
        f"发现 {len(issues)} 个阻塞项、{len(warnings)} 个提示。"
    )
    return {
        "ok": True,
        "status": status,
        "summary": summary,
        "package_id": pack_id,
        "version": version,
        "handlers": clean_handlers,
        "issues": issues,
        "warnings": warnings,
        "ready_for_packaging": not issues,
        "registry_consistent": registry_consistent,
        "evidence": [
            "input.manifest",
            "input.manifest.employee_config_v2.actions.handlers",
            *(["input.registry_record"] if isinstance(registry, dict) else []),
        ],
        "read_only": True,
        "side_effects": [],
        "meta": {
            "employee_id": EMPLOYEE_ID,
            "action": action,
            "workspace_root_present": bool(str((ctx or {}).get("workspace_root") or "")),
            "contract_version": "1.0",
        },
    }
