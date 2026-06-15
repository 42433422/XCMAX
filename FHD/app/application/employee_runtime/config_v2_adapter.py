# -*- coding: utf-8 -*-
"""将前端 employee_config_v2 富结构翻译为 employee_executor 可消费的配置。"""

from __future__ import annotations

import copy
from typing import Any


def _truthy_enabled(obj: Any) -> bool:
    return isinstance(obj, dict) and bool(obj.get("enabled"))


def _infer_perception_type(perc: dict[str, Any]) -> str | None:
    if not isinstance(perc, dict):
        return "text"
    explicit = str(perc.get("type") or "").strip().lower()
    if explicit in ("web_rankings", "ai_model_rankings"):
        return None
    if _truthy_enabled(perc.get("document")):
        return "document"
    if _truthy_enabled(perc.get("vision")):
        return "image"
    if explicit:
        return None
    return "text"


def _format_behavior_rules(rules: Any) -> str:
    if not isinstance(rules, list) or not rules:
        return ""
    lines: list[str] = []
    for i, item in enumerate(rules, 1):
        if isinstance(item, str) and item.strip():
            lines.append(f"{i}. {item.strip()}")
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("rule_id") or "").strip()
            desc = str(item.get("description") or item.get("text") or "").strip()
            if name and desc:
                lines.append(f"{i}. {name}: {desc}")
            elif name:
                lines.append(f"{i}. {name}")
            elif desc:
                lines.append(f"{i}. {desc}")
    if not lines:
        return ""
    return "【行为约束】\n" + "\n".join(lines)


def _format_few_shot(examples: Any) -> str:
    if not isinstance(examples, list) or not examples:
        return ""
    lines: list[str] = []
    for i, ex in enumerate(examples, 1):
        if isinstance(ex, str) and ex.strip():
            lines.append(f"示例{i}: {ex.strip()}")
        elif isinstance(ex, dict):
            inp = str(ex.get("input") or "").strip()
            out = str(ex.get("output") or "").strip()
            expl = str(ex.get("explanation") or "").strip()
            chunk = []
            if inp:
                chunk.append(f"输入: {inp}")
            if out:
                chunk.append(f"输出: {out}")
            if expl:
                chunk.append(f"说明: {expl}")
            if chunk:
                lines.append(f"示例{i}:\n" + "\n".join(chunk))
    if not lines:
        return ""
    return "【少样本示例】\n" + "\n\n".join(lines)


def _compose_role_block(role: Any) -> str:
    if not isinstance(role, dict):
        return ""
    parts: list[str] = []
    name = str(role.get("name") or "").strip()
    persona = str(role.get("persona") or "").strip()
    tone = str(role.get("tone") or "").strip()
    exp = role.get("expertise")
    if name:
        parts.append(f"名称: {name}")
    if persona:
        parts.append(f"人格: {persona}")
    if tone:
        parts.append(f"语气: {tone}")
    if isinstance(exp, list) and exp:
        parts.append("专长: " + ", ".join(str(x).strip() for x in exp if str(x).strip()))
    if not parts:
        return ""
    return "【角色设定】\n" + "\n".join(parts)


def _merge_system_prompt(agent: dict[str, Any]) -> str:
    base = str(agent.get("system_prompt") or "").strip()
    prefix_blocks = [
        _compose_role_block(agent.get("role")),
        _format_behavior_rules(agent.get("behavior_rules")),
        _format_few_shot(agent.get("few_shot_examples")),
    ]
    prefix = "\n\n".join(b for b in prefix_blocks if b)
    if prefix and base:
        return prefix + "\n\n" + base
    if base:
        return base
    if prefix:
        return prefix
    return "你是智能员工助手"


def _ensure_cognition_agent_shape(cognition: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(cognition, dict):
        cognition = {}
    out = copy.deepcopy(cognition)
    agent = out.get("agent")
    if not isinstance(agent, dict):
        legacy_prompt = out.get("system_prompt")
        out["agent"] = {
            "system_prompt": str(legacy_prompt or "").strip() or "你是智能员工助手",
            "model": (
                out.get("model")
                if isinstance(out.get("model"), dict)
                else {
                    "provider": "auto",
                    "model_name": "auto",
                    "max_tokens": 4000,
                }
            ),
        }
        for k in ("system_prompt", "reasoning_mode", "model"):
            out.pop(k, None)
        agent = out["agent"]
    agent = dict(agent)
    agent["system_prompt"] = _merge_system_prompt(agent)
    out["agent"] = agent
    return out


def _normalize_actions(actions: Any) -> dict[str, Any]:
    if not isinstance(actions, dict):
        return {"handlers": ["echo"]}
    out = copy.deepcopy(actions)
    handlers: list[str] = list(out.get("handlers") or [])
    if not handlers:
        handlers = ["echo"]
    vo = out.get("voice_output")
    if isinstance(vo, dict) and vo.get("enabled") and "voice_output" not in handlers:
        handlers.append("voice_output")
    out["handlers"] = handlers
    return out


def translate_v2_to_executor_config(v2: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(v2, dict):
        return {}
    out = copy.deepcopy(v2)
    perc = dict(out.get("perception") or {}) if isinstance(out.get("perception"), dict) else {}
    inferred = _infer_perception_type(perc)
    if inferred is not None:
        perc = {**perc, "type": inferred}
    out["perception"] = perc
    mem = out.get("memory")
    if mem is None or not isinstance(mem, dict):
        out["memory"] = {"type": "session"}
    else:
        out["memory"] = copy.deepcopy(mem)
    cog_in = out.get("cognition")
    if not isinstance(cog_in, dict):
        cog_in = {}
    out["cognition"] = _ensure_cognition_agent_shape(cog_in)
    out["actions"] = _normalize_actions(out.get("actions"))
    return out


def needs_executor_translation(v2: dict[str, Any]) -> bool:
    if not isinstance(v2, dict):
        return False
    if any(
        k in v2
        for k in ("identity", "collaboration", "management", "commerce", "workflow_employees")
    ):
        return True
    perc = v2.get("perception")
    if isinstance(perc, dict):
        if any(
            isinstance(perc.get(k), dict) and perc[k].get("enabled") is not None
            for k in ("vision", "document", "audio", "data_input", "event_listener")
        ):
            return True
    cog = v2.get("cognition")
    if isinstance(cog, dict):
        agent = cog.get("agent")
        if isinstance(agent, dict):
            if any(
                agent.get(x) is not None for x in ("role", "behavior_rules", "few_shot_examples")
            ):
                return True
    act = v2.get("actions")
    if (
        isinstance(act, dict)
        and isinstance(act.get("voice_output"), dict)
        and act["voice_output"].get("enabled")
    ):
        return True
    return False


__all__ = ["needs_executor_translation", "translate_v2_to_executor_config"]
