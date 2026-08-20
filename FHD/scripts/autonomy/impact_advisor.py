"""ImpactPredictor LLM 顾问轨——规则机之后的副作用推演。

设计：
- 规则 switch-case 仍是安全硬轨（fail-closed 对破坏性动作）
- 当 ``XCAGI_IMPACT_LLM=1`` 且规则结果 allow=True 但动作 risk=high 时，
  可选调用 LLM 追加 advisory reasons（默认不阻断，除非 XCAGI_IMPACT_LLM_BLOCK=1）
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def llm_advisory_enabled() -> bool:
    raw = (os.environ.get("XCAGI_IMPACT_LLM") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def llm_advisory_blocks() -> bool:
    raw = (os.environ.get("XCAGI_IMPACT_LLM_BLOCK") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


async def advise_impact(
    action: dict[str, Any],
    truth: dict[str, Any],
    *,
    rule_prediction: dict[str, Any],
) -> dict[str, Any]:
    """返回 advisory；失败时空建议。"""
    if not llm_advisory_enabled():
        return {
            "enabled": False,
            "allow": True,
            "reasons": [],
            "suggestions": [],
            "source": "disabled",
        }

    try:
        from app.domain.neuro.cognition.llm_port import get_llm_port
    except RECOVERABLE_ERRORS:  # noqa: BLE001
        return {
            "enabled": True,
            "allow": True,
            "reasons": [],
            "suggestions": ["llm_port_unavailable"],
            "source": "unavailable",
        }

    port = get_llm_port()
    prompt = {
        "action": action,
        "truth": truth,
        "rule_prediction": rule_prediction,
        "task": "预测副作用；输出 JSON {allow:bool, reasons:[str], suggestions:[str]}",
    }
    text = await port.chat(
        [
            {
                "role": "system",
                "content": (
                    "你是运维副作用顾问。规则轨已给出初判。"
                    "只补充规则未覆盖的风险；不确定时 allow=true 并写明 uncertainty。"
                    "只输出 JSON。"
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)[:5000]},
        ],
        temperature=0.1,
        max_tokens=500,
    )
    parsed = _extract_json(text or "") or {}
    allow = bool(parsed.get("allow", True))
    reasons = [str(r) for r in (parsed.get("reasons") or []) if str(r).strip()][:8]
    suggestions = [str(s) for s in (parsed.get("suggestions") or []) if str(s).strip()][:8]
    return {
        "enabled": True,
        "allow": allow,
        "reasons": reasons,
        "suggestions": suggestions,
        "source": "llm",
        "blocks": llm_advisory_blocks(),
    }


def merge_predictions(
    rule: dict[str, Any],
    advisory: dict[str, Any],
) -> dict[str, Any]:
    """合并规则与顾问结果。"""
    reasons = list(rule.get("reasons") or [])
    suggestions = list(rule.get("suggestions") or [])
    allow = bool(rule.get("allow", True))
    if advisory.get("enabled") and advisory.get("source") == "llm":
        for r in advisory.get("reasons") or []:
            reasons.append(f"[llm-advisory] {r}")
        for s in advisory.get("suggestions") or []:
            suggestions.append(s)
        if advisory.get("blocks") and advisory.get("allow") is False:
            allow = False
    return {
        "allow": allow,
        "reasons": reasons,
        "suggestions": suggestions,
        "advisory": advisory,
    }
