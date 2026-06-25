"""Runtime employee policy overrides produced by health/evolution loops.

The policy is intentionally file-backed so employee self-learning can affect
the next execution without mutating packaged manifests or requiring a DB
migration.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

DEFAULT_POLICY_NAME = "employee_runtime_policy.json"


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or Path.home() / ".xcmax" / "modstore-daily")


def policy_path() -> Path:
    raw = os.environ.get("MODSTORE_EMPLOYEE_RUNTIME_POLICY_FILE")
    return Path(raw).expanduser() if raw else _runtime_dir() / DEFAULT_POLICY_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_policy() -> Dict[str, Any]:
    path = policy_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"employees": {}, "schema_version": 1}
    except FileNotFoundError:
        return {"employees": {}, "schema_version": 1}
    except Exception:
        return {"employees": {}, "schema_version": 1}


def save_policy(policy: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(policy or {})
    payload.setdefault("schema_version", 1)
    payload["updated_at"] = _now_iso()
    path = policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp.replace(path)
    return {**payload, "path": str(path)}


def record_employee_degradation(
    *,
    employee_id: str,
    fail_count: int,
    lookback_hours: int,
    reason: str,
    severity: str = "warn",
) -> Dict[str, Any]:
    eid = str(employee_id or "").strip()
    if not eid:
        return {"ok": False, "reason": "empty_employee_id"}
    policy = load_policy()
    employees = policy.get("employees")
    if not isinstance(employees, dict):
        employees = {}
    fallback_provider = (os.environ.get("MODSTORE_EMPLOYEE_FALLBACK_PROVIDER") or "auto").strip()
    fallback_model = (os.environ.get("MODSTORE_EMPLOYEE_FALLBACK_MODEL") or "auto").strip()
    temperature = 0.1 if severity == "deactivate" else 0.2
    row = {
        "fail_count": int(fail_count or 0),
        "lookback_hours": int(lookback_hours or 0),
        "max_tokens_multiplier": 0.8 if severity == "deactivate" else 0.9,
        "model_name": fallback_model,
        "provider": fallback_provider,
        "reason": str(reason or "")[:1000],
        "severity": severity,
        "system_prompt_append": (
            "Runtime self-learning policy: use conservative, deterministic, minimal-risk "
            "execution. Prefer smaller scoped changes and explicit error reporting."
        ),
        "temperature": temperature,
        "updated_at": _now_iso(),
    }
    employees[eid] = row
    policy["employees"] = employees
    saved = save_policy(policy)
    return {"ok": True, "employee_id": eid, "policy": row, "path": saved.get("path")}


def policy_for_employee(employee_id: str) -> Dict[str, Any]:
    employees = load_policy().get("employees")
    if not isinstance(employees, dict):
        return {}
    row = employees.get(str(employee_id or "").strip())
    return row if isinstance(row, dict) else {}


def apply_policy_to_config(
    employee_id: str, config: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    policy = policy_for_employee(employee_id)
    if not policy or not isinstance(config, dict):
        return config, {}
    cog = config.get("cognition")
    if not isinstance(cog, dict):
        return config, policy
    agent = cog.get("agent") if isinstance(cog.get("agent"), dict) else cog
    if not isinstance(agent, dict):
        return config, policy
    model = agent.get("model")
    if not isinstance(model, dict):
        model = {}
        agent["model"] = model
    provider = str(policy.get("provider") or "").strip()
    model_name = str(policy.get("model_name") or "").strip()
    if provider:
        model["provider"] = provider
    if model_name:
        model["model_name"] = model_name
    if policy.get("temperature") is not None:
        model["temperature"] = float(policy.get("temperature") or 0.2)
    try:
        multiplier = float(policy.get("max_tokens_multiplier") or 1.0)
        if multiplier > 0 and model.get("max_tokens"):
            model["max_tokens"] = max(512, int(int(model.get("max_tokens") or 4000) * multiplier))
    except Exception:
        pass
    append = str(policy.get("system_prompt_append") or "").strip()
    if append:
        current = str(agent.get("system_prompt") or cog.get("system_prompt") or "")
        if append not in current:
            agent["system_prompt"] = f"{current.rstrip()}\n\n{append}".strip()
    return config, policy


__all__ = [
    "apply_policy_to_config",
    "load_policy",
    "policy_for_employee",
    "policy_path",
    "record_employee_degradation",
    "save_policy",
]
