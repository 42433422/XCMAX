"""Rule-based adaptation and serialization helpers for ESkill runtime."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from string import Template
from typing import Any, Dict


def loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def render_template(template: str, values: Dict[str, Any]) -> str:
    flat = {str(key): "" if value is None else str(value) for key, value in values.items()}
    rendered = Template(template or "").safe_substitute(flat)
    return re.sub(r"\s+", " ", rendered).strip()


class RuleBasedESkillAdapter:
    """Strategy-engine adapter; replaceable with an LLM implementation."""

    def propose_patch(
        self,
        *,
        reason: str,
        logic: Dict[str, Any],
        input_data: Dict[str, Any],
        history: list[Dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> Dict[str, Any]:
        history = history or []
        changes: Dict[str, Any] = {
            "metadata": {"adapted_for": reason, "history_matches": len(history)}
        }
        logic_type = str(logic.get("type") or "template_transform")
        if error:
            changes["metadata"]["last_error"] = str(error)
        if input_data.get("details"):
            changes["metadata"]["used_details"] = True
        for prior in history:
            prior_changes = prior.get("changes")
            if isinstance(prior_changes, dict):
                changes.update(
                    {key: value for key, value in prior_changes.items() if key != "metadata"}
                )
                changes["metadata"]["reused_patch"] = True
                return {
                    "reason": reason,
                    "strategy": "history_reuse",
                    "changes": changes,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
        if logic_type == "template_transform":
            changes["template"] = (
                logic.get("dynamic_template")
                or logic.get("fallback_template")
                or logic.get("template")
                or "Dynamic result: ${details}"
            )
            changes["required_fields"] = []
            if bool(logic.get("allow_steps")):
                changes["type"] = "pipeline"
                changes["steps"] = [
                    {
                        "id": "render_dynamic_template",
                        "type": "template_transform",
                        "template": changes["template"],
                        "output_var": str(logic.get("output_var") or "eskill_result"),
                    },
                    {
                        "id": "attach_adaptation_reason",
                        "type": "set_value",
                        "output_var": "adaptation_reason",
                        "value": reason,
                    },
                ]
        elif logic_type == "employee_task":
            task = str(logic.get("task_template") or logic.get("task") or "")
            changes["task_template"] = (
                f"{task}\n请适配当前特殊场景：${{details}}".strip()
                if task
                else "请根据输入完成任务，并适配特殊场景：${details}"
            )
            changes["retry_count"] = max(int(logic.get("retry_count") or 0), 1)
        else:
            changes["type"] = "template_transform"
            changes["template"] = "Dynamic result: ${details}"
            changes["required_fields"] = []
        return {
            "reason": reason,
            "strategy": "rule_based_structured_patch",
            "changes": changes,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
