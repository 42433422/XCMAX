"""Deterministic skill-step derivation and fallback source generation."""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List

MAX_STEPS = 6


def sanitize_identifier(text: str, fallback: str = "skill") -> str:
    raw = re.sub(r"[^a-z0-9_]+", "_", (text or "").lower())
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw[:48] or fallback


def _dedupe_key(text: str) -> str:
    raw = re.sub(r"\s+", "", str(text or "").strip().lower())
    return raw or sanitize_identifier(text, "skill")


def extract_function_name(source: str) -> str:
    match = re.search(r"^\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)", source, re.MULTILINE)
    return match.group(1) if match else "execute"


def make_vibe_skill_id(name: str, suffix: str = "") -> str:
    base = sanitize_identifier(name, "emp_skill")
    unique = uuid.uuid4().hex[:8]
    return f"{base}_{unique}" if not suffix else f"{base}_{suffix}_{unique}"


def fallback_step_script(step: Dict[str, Any], employee_fn: str) -> str:
    function_name = sanitize_identifier(step["name"], "step") or "execute"
    output_variable = step.get("output_var") or "result"
    input_keys = step.get("input_keys") or []
    arguments = (
        ", ".join(f"{key}=kwargs.get({key!r})" for key in input_keys) if input_keys else "**kwargs"
    )
    return f'''\
def {function_name}(**kwargs):
    """
    {step['sub_brief']}
    Auto-generated wrapper; will be upgraded by vibe-coding if LLM is available.
    """
    try:
        from employees import {employee_fn}  # type: ignore
        raw = {employee_fn}({arguments})
    except Exception as exc:
        return {{"ok": False, "error": str(exc), "{output_variable}": None}}
    return {{"ok": True, "{output_variable}": raw}}
'''


def manifest_skill_steps(
    manifest: Dict[str, Any], brief: str, panel_summary: str
) -> List[Dict[str, Any]]:
    raw_items: List[Dict[str, Any]] = []
    config = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    cognition = config.get("cognition") if isinstance(config.get("cognition"), dict) else {}
    skills = cognition.get("skills") if isinstance(cognition.get("skills"), list) else []
    for item in skills:
        if isinstance(item, dict):
            raw_items.append(
                {
                    "name": str(item.get("name") or "").strip(),
                    "brief": str(item.get("brief") or item.get("description") or "").strip(),
                    "domain": str(item.get("domain") or "").strip(),
                }
            )
    metadata = config.get("metadata") if isinstance(config.get("metadata"), dict) else {}
    suggested = (
        metadata.get("suggested_skills")
        if isinstance(metadata.get("suggested_skills"), list)
        else []
    )
    for item in suggested:
        if isinstance(item, dict):
            raw_items.append(
                {
                    "name": str(item.get("name") or "").strip(),
                    "brief": str(item.get("brief") or item.get("description") or "").strip(),
                    "domain": str(item.get("domain") or "").strip(),
                }
            )
    employee = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    capabilities = (
        employee.get("capabilities") if isinstance(employee.get("capabilities"), list) else []
    )
    for capability in capabilities:
        text = str(capability or "").strip()
        if text:
            raw_items.append({"name": text, "brief": text, "domain": text})

    seen: set[str] = set()
    steps: List[Dict[str, Any]] = []
    context = panel_summary or brief
    for item in raw_items:
        name = item["name"] or item["brief"]
        if not name:
            continue
        key = _dedupe_key(name)
        if key in seen:
            continue
        seen.add(key)
        description = item["brief"] or name
        steps.append(
            {
                "name": name[:64],
                "sub_brief": (
                    f"实现员工能力「{name}」：{description}。员工整体任务背景：{context[:500]}。"
                    "输入为 dict payload，返回 dict，包含处理结果、依据和错误信息。"
                )[:600],
                "input_keys": ["payload"],
                "output_var": sanitize_identifier(name, "skill_result")[:40],
                "domain": item["domain"] or name,
            }
        )
        if len(steps) >= MAX_STEPS:
            break
    return steps


def brief_skill_steps(brief: str, panel_summary: str) -> List[Dict[str, Any]]:
    text = "。".join(value for value in [brief, panel_summary] if value)
    parts = [
        part.strip(" ，,;；。") for part in re.split(r"[；;。\n]+", text) if part.strip(" ，,;；。")
    ]
    if len(parts) <= 1 and any(keyword in text for keyword in ("并", "和", "、", "，")):
        parts = [
            part.strip(" ，,;；。")
            for part in re.split(r"[、，,]|并|和", text)
            if part.strip(" ，,;；。")
        ]
    steps: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for part in parts:
        if len(part) < 4:
            continue
        key = _dedupe_key(part)
        if key in seen:
            continue
        seen.add(key)
        steps.append(
            {
                "name": part[:24],
                "sub_brief": (
                    f"实现员工子能力：{part}。输入为 dict payload，返回 dict，"
                    "包含处理结果、依据、错误信息和下一步建议。"
                )[:500],
                "input_keys": ["payload"],
                "output_var": sanitize_identifier(part, "skill_result")[:40],
                "domain": part[:80],
            }
        )
        if len(steps) >= MAX_STEPS:
            break
    return steps if len(steps) >= 2 else []
