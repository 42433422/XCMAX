"""Parsing and normalization for LLM-generated MOD manifests."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from modman.manifest_util import validate_manifest_dict

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def normalize_mod_id(value: str) -> Optional[str]:
    normalized = str(value or "").strip().lower()
    if not normalized or not _ID_RE.match(normalized):
        return None
    return normalized


def strip_json_fence(text: str) -> str:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```\s*$", "", stripped)
    return stripped.strip()


def extract_json_text(content: str) -> str:
    """Extract a JSON object from fenced or lightly decorated model output."""
    text = (content or "").replace("\ufeff", "").strip()
    if not text:
        return ""
    match = _JSON_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    stripped = strip_json_fence(text)
    if stripped.startswith("{"):
        return stripped
    brace = text.find("{")
    if brace != -1:
        candidate = text[brace:].strip()
        closing_brace = candidate.rfind("}")
        if closing_brace > 0:
            return candidate[: closing_brace + 1].strip()
    return stripped


def parse_llm_manifest_json(content: str) -> Tuple[Optional[Dict[str, Any]], str]:
    raw = extract_json_text(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"模型返回非合法 JSON: {exc}"
    if not isinstance(data, dict):
        return None, "JSON 根须为对象"
    mod_id = str(data.get("id") or "").strip().lower()
    if not mod_id or not _ID_RE.match(mod_id):
        return None, "id 无效：须匹配小写字母/数字/._- 且不以连字符开头"
    name = str(data.get("name") or mod_id).strip() or mod_id
    version = str(data.get("version") or "1.0.0").strip() or "1.0.0"
    description = str(data.get("description") or "").strip()
    workflow_employees: List[Dict[str, Any]] = []
    input_employees = data.get("workflow_employees")
    if isinstance(input_employees, list):
        for index, item in enumerate(input_employees):
            if not isinstance(item, dict):
                continue
            employee_id = str(item.get("id") or "").strip()
            label = str(item.get("label") or "").strip()
            panel_title = str(item.get("panel_title") or "").strip()
            panel_summary = str(item.get("panel_summary") or "").strip()
            if not employee_id and not label and not panel_title:
                continue
            workflow_employees.append(
                {
                    "id": employee_id or f"{mod_id}-wf-{index + 1}",
                    "label": label or panel_title or employee_id,
                    "panel_title": panel_title or label or employee_id,
                    "panel_summary": panel_summary or description[:240],
                }
            )
    manifest: Dict[str, Any] = {
        "id": mod_id,
        "name": name,
        "version": version,
        "author": "",
        "description": description,
        "primary": False,
        "dependencies": {"xcagi": ">=1.0.0"},
        "backend": {"entry": "blueprints", "init": "mod_init"},
        "frontend": {
            "routes": "frontend/routes",
            "menu": [
                {
                    "id": f"{mod_id}-home",
                    "label": name,
                    "icon": "fa-cube",
                    "path": f"/{mod_id}",
                }
            ],
        },
        "hooks": {},
        "comms": {"exports": []},
    }
    if workflow_employees:
        manifest["workflow_employees"] = workflow_employees
    validation_errors = validate_manifest_dict(manifest)
    if validation_errors:
        return None, "manifest 校验: " + "; ".join(validation_errors)
    return manifest, ""
