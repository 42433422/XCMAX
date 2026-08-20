"""Deterministic, read-only intake contract for employee interviews."""

from __future__ import annotations

from typing import Any, Dict, Iterable

EMPLOYEE_ID = "employee-interview-assistant"
_REQUIRED_ROLE_FIELDS = (
    "mission",
    "capabilities",
    "dependencies",
    "risk_level",
    "handlers",
)
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "id_card",
    "bank_card",
    "身份证",
    "银行卡",
}


def _clean_text(value: Any, *, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _clean_string_list(value: Any, *, limit: int = 40) -> list[str]:
    if isinstance(value, str):
        values: Iterable[Any] = [value]
    elif isinstance(value, list | tuple | set):
        values = value
    else:
        values = []
    out: list[str] = []
    for item in values:
        text = _clean_text(item, limit=160)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key or "").strip().lower()
            if normalized in _SENSITIVE_KEYS or _contains_sensitive_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _failure(message: str, *, code: str) -> Dict[str, Any]:
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


def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Build a structured interview gap report without storing personal data."""

    data = dict(payload or {})
    action = _clean_text(data.get("action") or "draft_interview", limit=80)
    if action != "draft_interview":
        return _failure(f"unsupported action: {action}", code="unsupported_action")
    if _contains_sensitive_key(data):
        return _failure(
            "输入包含禁止收集的密钥、令牌或个人敏感字段",
            code="sensitive_input_blocked",
        )

    target_employee_id = _clean_text(
        data.get("target_employee_id") or data.get("employee_id"), limit=160
    )
    role_context = data.get("role_context")
    if not target_employee_id:
        return _failure("target_employee_id is required", code="missing_target_employee_id")
    if not isinstance(role_context, dict):
        return _failure("role_context object is required", code="missing_role_context")

    normalized = {
        "mission": _clean_text(role_context.get("mission"), limit=800),
        "capabilities": _clean_string_list(role_context.get("capabilities")),
        "dependencies": _clean_string_list(role_context.get("dependencies")),
        "risk_level": _clean_text(role_context.get("risk_level"), limit=32).lower(),
        "handlers": _clean_string_list(role_context.get("handlers")),
    }
    missing_fields = [field for field in _REQUIRED_ROLE_FIELDS if not normalized[field]]
    questions: list[dict[str, str]] = []
    question_text = {
        "mission": "这个岗位交付的可验证结果是什么？",
        "capabilities": "完成职责所需的具体能力有哪些？",
        "dependencies": "它依赖哪些上游员工、数据或系统？",
        "risk_level": "岗位风险等级及需要审批的动作是什么？",
        "handlers": "运行时由哪些 actions.handlers 承载真实能力？",
    }
    for field in missing_fields:
        questions.append(
            {
                "field": field,
                "purpose": "补全岗位运行契约",
                "question": question_text[field],
            }
        )

    responses = data.get("responses") if isinstance(data.get("responses"), dict) else {}
    response_fields = sorted(
        str(key)[:80]
        for key, value in responses.items()
        if str(key).strip() and value not in (None, "", [], {})
    )[:50]
    completed = len(_REQUIRED_ROLE_FIELDS) - len(missing_fields)
    coverage_pct = round(completed * 100 / len(_REQUIRED_ROLE_FIELDS), 2)
    status = "success" if not missing_fields else "needs_input"
    summary = (
        f"岗位 {target_employee_id} 的访谈契约已核对："
        f"{completed}/{len(_REQUIRED_ROLE_FIELDS)} 个核心字段完整，"
        f"仍需补充 {len(missing_fields)} 项。"
    )
    return {
        "ok": True,
        "status": status,
        "summary": summary,
        "target_employee_id": target_employee_id,
        "coverage_pct": coverage_pct,
        "normalized_role_context": normalized,
        "missing_fields": missing_fields,
        "questions": questions,
        "response_fields_received": response_fields,
        "evidence": [
            "input.target_employee_id",
            *[f"input.role_context.{field}" for field in _REQUIRED_ROLE_FIELDS],
        ],
        "warnings": (["存在待补字段；本回执不代表岗位已完成入职"] if missing_fields else []),
        "read_only": True,
        "side_effects": [],
        "meta": {
            "employee_id": EMPLOYEE_ID,
            "action": action,
            "workspace_root_present": bool(str((ctx or {}).get("workspace_root") or "")),
            "contract_version": "1.0",
        },
    }
