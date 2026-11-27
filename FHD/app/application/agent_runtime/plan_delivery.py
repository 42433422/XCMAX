"""Structured, non-executing delivery of a plan bound to the current catalogs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from mimetypes import guess_type
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.task_lifecycle.agent_runtime_contract import (
    PlanToolAction,
    canonical_digest,
    plan_navigation_entries,
)


class NavigationStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["navigation"]
    navigation_id: str
    inputs: dict[str, str] = Field(description="建议手填值，由用户在页面核对")


class ToolStep(PlanToolAction):
    kind: Literal["tool"]


Step = Annotated[ToolStep | NavigationStep, Field(discriminator="kind")]


class ActionSteps(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["steps"]
    steps: list[Step] = Field(min_length=1, max_length=32)
    notes: list[str] = Field(
        default_factory=list, max_length=8, description="不包含具体工具声明的说明"
    )


class NarrativePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["narrative"]
    steps: list[str] = Field(
        min_length=1,
        max_length=32,
        description="不依赖具体产品能力或界面入口的文字步骤",
    )


class UnavailablePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["unavailable"]
    reason: Literal["missing_input", "missing_access", "unverified_entry"]


class PlanDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan: Annotated[ActionSteps | NarrativePlan | UnavailablePlan, Field(discriminator="kind")]


@dataclass(frozen=True)
class PlanVerdict:
    output: str = ""
    proof: dict[str, Any] | None = None
    error: str = ""
    unavailable: bool = False


def plan_delivery_schema(binding: Any) -> dict[str, Any]:
    """Project complete variants to the native Responses schema."""
    from app.infrastructure.xiaox.tools import XiaoxToolBridge

    schema = PlanDelivery.model_json_schema()
    definitions = schema["$defs"]
    plan = schema["properties"]["plan"]
    steps = definitions["ActionSteps"]["properties"]["steps"]["items"]
    for variant in (plan, steps):
        variant["anyOf"] = variant.pop("oneOf")
        variant.pop("discriminator")
    for definition in definitions.values():
        kind = definition.get("properties", {}).get("kind", {})
        if "const" in kind:
            kind["enum"] = [kind.pop("const")]

    specs = list(XiaoxToolBridge.visible_actions(binding, []))
    entries = plan_navigation_entries(binding.run.metadata["runtime_goal_contract"])
    # Keep the catalog constraints on each complete object. A provider
    # projecting the step variants must never see a partial tool shape.
    # The host still validates the exact tool/action pair.
    if specs:
        tool = definitions["ToolStep"]["properties"]
        tool["tool_id"]["enum"] = sorted({spec.tool_id for spec in specs})
        tool["action"]["enum"] = sorted({spec.action for spec in specs})
    else:
        steps["anyOf"].remove({"$ref": "#/$defs/ToolStep"})
        del definitions["ToolStep"]
    if entries:
        definitions["NavigationStep"]["properties"]["navigation_id"]["enum"] = [
            item["id"] for item in entries
        ]
    else:
        steps["anyOf"].remove({"$ref": "#/$defs/NavigationStep"})
        del definitions["NavigationStep"]
    if not steps["anyOf"]:
        plan["anyOf"].remove({"$ref": "#/$defs/ActionSteps"})
        del definitions["ActionSteps"]
    return schema


def _unbound_product_symbol(texts: list[str], contract: dict[str, Any]) -> bool:
    """Guard explicit, code-styled references in the product's tool namespace."""
    from app.application.agent_orchestrator.tool_spec import build_tool_specs_v2

    quoted = {part.strip() for text in texts for part in text.split("`")[1::2] if "." in part}
    if not quoted:
        return False
    file_names = {
        attachment.get("name") for attachment in contract["request"].get("attachments") or []
    }
    actions = build_tool_specs_v2()
    fields: dict[str, set[str]] = {}
    for (tool_id, _action), spec in actions.items():
        fields.setdefault(tool_id, set()).update(spec.input_schema.get("properties", {}).keys())
    for symbol in quoted - file_names:
        tool_id, _, action = symbol.rpartition(".")
        if tool_id not in fields or not action.isidentifier():
            continue
        if (tool_id, action) in actions or (
            action not in fields[tool_id] and guess_type(symbol)[0] is None
        ):
            return True
    return False


def _plan_arguments(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).replace(
        "`", "\\u0060"
    )


def render_action_plan(binding: Any, output: str) -> PlanVerdict:
    """Produce the only displayed steps, using validated identities and parameters."""
    from app.application.agent_runtime.goal_verifier import (
        _unique_json_object,
        _verify_plan_capabilities,
    )

    try:
        decoded = json.loads(output, object_pairs_hook=_unique_json_object)
        json.dumps(decoded, allow_nan=False)
        plan = PlanDelivery.model_validate(decoded).plan
    except (ValueError, ValidationError):
        return PlanVerdict(error="方案交付缺少可核对的结构。")
    if isinstance(plan, UnavailablePlan):
        explanations = {
            "missing_input": "现有资料不足以确认可用方案，请补充任务所需信息。",
            "missing_access": "当前账号的可用权限不足以确认方案，请核对账号或授权范围。",
            "unverified_entry": "当前能力目录与导航中尚未核实适用入口。",
        }
        return PlanVerdict(output=explanations[plan.reason], unavailable=True)
    contract = binding.run.metadata["runtime_goal_contract"]
    prose = plan.steps if isinstance(plan, NarrativePlan) else plan.notes
    if _unbound_product_symbol(prose, contract):
        return PlanVerdict(error="方案中的产品工具标识需要作为独立动作按当前契约核对。")
    if any(not step.strip() or len(step) > 4000 for step in prose):
        return PlanVerdict(error="文字说明包含无法交付的步骤。")
    if isinstance(plan, NarrativePlan):
        lines = [
            "**文字方案**",
            *(f"{i}. {step}" for i, step in enumerate(plan.steps, 1)),
        ]
        evidence = {"kind": "narrative", "steps": len(plan.steps)}
    else:
        nav = {item["id"]: item for item in plan_navigation_entries(contract)}
        calls = [
            step.model_dump(exclude={"kind"}) for step in plan.steps if isinstance(step, ToolStep)
        ]
        proofs, error = (
            _verify_plan_capabilities(binding, calls, require_documented_params=True)
            if calls
            else ([], "")
        )
        if error:
            return PlanVerdict(error=error)
        lines = ["**能力调用方案**"]
        links = []
        for i, step in enumerate(plan.steps, 1):
            if isinstance(step, ToolStep):
                args = _plan_arguments(step.params)
                approvable = "需要审批" if step.approval_required else "无需业务审批"
                dependency = f"。依赖 {', '.join(step.depends_on)}" if step.depends_on else ""
                lines.append(
                    f"{i}. `{step.tool_id}.{step.action}`，参数 `{args}`，{approvable}{dependency}。"
                )
            else:
                entry = nav.get(step.navigation_id)
                if entry is None:
                    return PlanVerdict(error="方案引用了当前导航目录中没有的入口。")
                path = " → ".join([*entry["breadcrumb"], entry["label"]])
                args = _plan_arguments(step.inputs)
                suffix = f"，建议手填 `{args}`（在页面核对）" if step.inputs else ""
                lines.append(f"{i}. 手动打开 {path}{suffix}，页面打开无需业务审批。")
                links.append(entry["id"])
        lines.extend(f"说明：{note}" for note in plan.notes)
        evidence = {"kind": "steps", "tools": proofs, "navigation": links}
    rendered = "\n\n".join(lines)
    return PlanVerdict(
        output=rendered,
        proof={
            **evidence,
            "goal_digest": contract["digest"],
            "response_digest": canonical_digest(rendered),
        },
    )
