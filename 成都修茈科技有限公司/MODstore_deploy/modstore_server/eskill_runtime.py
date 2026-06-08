"""ESkill runtime: static-first execution with controlled dynamic solidification."""

from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from datetime import datetime, timezone
from string import Template
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from modstore_server.models import ESkill, ESkillRun, ESkillVersion
from modstore_server.workflow_variables import resolve_value


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return default


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _render_template(template: str, values: Dict[str, Any]) -> str:
    flat = {str(k): "" if v is None else str(v) for k, v in values.items()}
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
            "metadata": {
                "adapted_for": reason,
                "history_matches": len(history),
            }
        }
        logic_type = str(logic.get("type") or "template_transform")
        if error:
            changes["metadata"]["last_error"] = str(error)
        if input_data.get("details"):
            changes["metadata"]["used_details"] = True

        for prior in history:
            prior_changes = prior.get("changes")
            if isinstance(prior_changes, dict):
                changes.update({k: v for k, v in prior_changes.items() if k != "metadata"})
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
                f"{task}\n请适配当前特殊场景：${details}".strip()
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


class ESkillRuntime:
    def __init__(self, adapter: Optional[RuleBasedESkillAdapter] = None):
        self.adapter = adapter or RuleBasedESkillAdapter()

    def run(
        self,
        db: Session,
        *,
        eskill_id: int,
        user_id: int,
        input_data: Dict[str, Any],
        workflow_id: int | None = None,  # 同画布 Skill 组 id（workflows.id）
        workflow_node_id: int | None = None,
        logic_overrides: Dict[str, Any] | None = None,
        trigger_policy_override: Dict[str, Any] | None = None,
        quality_gate_override: Dict[str, Any] | None = None,
        force_dynamic: bool = False,
        solidify: bool = True,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        skill = (
            db.query(ESkill)
            .filter(ESkill.id == eskill_id, ESkill.user_id == int(user_id or 0))
            .first()
        )
        if not skill:
            raise ValueError(f"ESkill 不存在或无权访问: {eskill_id}")
        version = (
            db.query(ESkillVersion)
            .filter(
                ESkillVersion.eskill_id == skill.id,
                ESkillVersion.version == skill.active_version,
            )
            .first()
        )
        if not version:
            raise ValueError(f"ESkill {eskill_id} 缺少 active version")

        base_logic = _loads(version.static_logic_json, {})
        logic = self._merge_overrides(base_logic, logic_overrides or {})
        trigger_policy = {
            **_loads(version.trigger_policy_json, {}),
            **(trigger_policy_override or {}),
        }
        quality_gate = {
            **_loads(version.quality_gate_json, {}),
            **(quality_gate_override or {}),
        }

        run = ESkillRun(
            eskill_id=skill.id,
            user_id=int(user_id or 0),
            workflow_id=workflow_id,
            workflow_node_id=workflow_node_id,
            stage="static",
            input_json=_dumps(input_data),
            started_at=datetime.now(timezone.utc),
        )

        try:
            output = self._execute_logic(logic, input_data, user_id=user_id)
            quality_ok = self._passes_quality_gate(output, quality_gate)
            if quality_ok and not force_dynamic and not bool(trigger_policy.get("force_dynamic")):
                return self._finish_run(db, run, output, t0, "static")
            if not bool(trigger_policy.get("on_quality_below_threshold", True)):
                return self._finish_run(db, run, output, t0, "static_quality_failed")
            return self._run_dynamic(
                db,
                skill,
                version,
                run,
                logic,
                input_data,
                t0,
                reason="force_dynamic" if force_dynamic else "quality_gate",
                user_id=user_id,
                error=None,
                quality_gate=quality_gate,
                solidify=solidify,
            )
        except Exception as exc:  # noqa: BLE001
            if not bool(trigger_policy.get("on_error", True)):
                return self._finish_run(db, run, {}, t0, "static_error", error=str(exc))
            return self._run_dynamic(
                db,
                skill,
                version,
                run,
                logic,
                input_data,
                t0,
                reason="error",
                user_id=user_id,
                error=exc,
                quality_gate=quality_gate,
                solidify=solidify,
            )

    def _run_dynamic(
        self,
        db: Session,
        skill: ESkill,
        version: ESkillVersion,
        run: ESkillRun,
        logic: Dict[str, Any],
        input_data: Dict[str, Any],
        t0: float,
        *,
        reason: str,
        user_id: int,
        error: Exception | None,
        quality_gate: Dict[str, Any],
        solidify: bool,
    ) -> Dict[str, Any]:
        if not self._is_within_domain(skill, logic, input_data):
            return self._finish_run(
                db,
                run,
                {},
                t0,
                "domain_rejected",
                error="动态阶段拒绝：输入或错误场景超出该 Skill 的领域边界",
            )
        history = self._retrieve_success_history(db, skill.id, input_data)
        patch = self.adapter.propose_patch(
            reason=reason,
            logic=logic,
            input_data=input_data,
            history=history,
            error=error,
        )
        patched_logic = self._apply_patch(logic, patch)
        try:
            output = self._execute_logic(patched_logic, input_data, user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            if self._rollback_to_previous_version(db, skill):
                db.commit()
            return self._finish_run(
                db,
                run,
                {},
                t0,
                "rollback_or_ai_intervention",
                patch=patch,
                error=str(exc),
            )

        quality = self._quality_report(output, quality_gate)
        if not quality["passed"]:
            patch["quality_report"] = quality
            if self._rollback_to_previous_version(db, skill):
                db.commit()
            return self._finish_run(
                db,
                run,
                output,
                t0,
                "rollback_or_ai_intervention",
                patch=patch,
                error="动态补丁沙箱验证未通过质量门控",
            )

        patch["quality_report"] = quality
        result = self._finish_run(db, run, output, t0, "dynamic", patch=patch, commit=False)
        if solidify:
            db.add(run)
            db.flush()
            next_version = int(skill.active_version or version.version or 0) + 1
            db.add(
                ESkillVersion(
                    eskill_id=skill.id,
                    version=next_version,
                    static_logic_json=_dumps(patched_logic),
                    trigger_policy_json=version.trigger_policy_json,
                    quality_gate_json=version.quality_gate_json,
                    source_run_id=run.id,
                    note=f"solidified from {reason}",
                )
            )
            skill.active_version = next_version
            skill.updated_at = datetime.now(timezone.utc)
            run.stage = "solidified"
            run.output_json = _dumps({**output, "solidified_version": next_version})
            db.commit()
            db.refresh(run)
            result = self._run_to_result(run)
        return result

    def _finish_run(
        self,
        db: Session,
        run: ESkillRun,
        output: Dict[str, Any],
        t0: float,
        stage: str,
        *,
        patch: Dict[str, Any] | None = None,
        error: str = "",
        commit: bool = True,
    ) -> Dict[str, Any]:
        run.stage = stage
        run.output_json = _dumps(output)
        run.patch_json = _dumps(patch or {})
        run.error_message = error
        run.duration_ms = round((time.perf_counter() - t0) * 1000, 3)
        run.completed_at = datetime.now(timezone.utc)
        if commit:
            db.add(run)
            db.commit()
            db.refresh(run)
        return self._run_to_result(run)

    def _run_to_result(self, run: ESkillRun) -> Dict[str, Any]:
        return {
            "run_id": run.id,
            "eskill_id": run.eskill_id,
            "stage": run.stage,
            "output": _loads(run.output_json, {}),
            "patch": _loads(run.patch_json, {}),
            "error": run.error_message or "",
            "duration_ms": run.duration_ms,
        }

    def _execute_logic(
        self,
        logic: Dict[str, Any],
        input_data: Dict[str, Any],
        *,
        user_id: int,
    ) -> Dict[str, Any]:
        logic_type = str(logic.get("type") or "template_transform")
        required = [str(x) for x in (logic.get("required_fields") or [])]
        missing = [key for key in required if input_data.get(key) in (None, "")]
        if missing:
            raise ValueError(f"ESkill 缺少必要输入: {', '.join(missing)}")

        if logic_type == "template_transform":
            output_var = str(logic.get("output_var") or "eskill_result")
            return {
                output_var: _render_template(str(logic.get("template") or ""), input_data),
                "eskill_logic_type": logic_type,
            }

        if logic_type == "employee_task":
            from modstore_server.services.employee import get_default_employee_client

            employee_id = str(logic.get("employee_id") or "")
            if not employee_id:
                raise ValueError("employee_task ESkill 缺少 employee_id")
            task_template = str(logic.get("task_template") or logic.get("task") or "")
            task = _render_template(task_template, input_data)
            result = get_default_employee_client().execute_task(
                employee_id=employee_id,
                task=task,
                input_data=input_data,
                user_id=user_id,
            )
            output_mapping = logic.get("output_mapping") or {}
            mapped = resolve_value(output_mapping, {"result": result, "global": input_data})
            base = {"employee_result": result, "eskill_logic_type": logic_type}
            if isinstance(mapped, dict):
                base.update(mapped)
            return base

        if logic_type == "pipeline":
            return self._execute_pipeline(logic, input_data, user_id=user_id)

        if logic_type in ("vibe_code", "vibe_workflow"):
            from modstore_server.integrations.vibe_eskill_adapter import execute_vibe_kind

            return execute_vibe_kind(logic, input_data, user_id=user_id)

        raise ValueError(f"不支持的 ESkill 静态逻辑类型: {logic_type}")

    def _execute_pipeline(
        self,
        logic: Dict[str, Any],
        input_data: Dict[str, Any],
        *,
        user_id: int,
    ) -> Dict[str, Any]:
        context: Dict[str, Any] = {**input_data}
        outputs: Dict[str, Any] = {"eskill_logic_type": "pipeline"}
        steps = logic.get("steps") or []
        if not isinstance(steps, list):
            raise ValueError("pipeline ESkill 的 steps 必须是数组")
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"pipeline step #{idx} 必须是对象")
            step_type = str(step.get("type") or "template_transform")
            output_var = str(step.get("output_var") or step.get("id") or f"step_{idx}")
            if step_type == "template_transform":
                value = _render_template(str(step.get("template") or ""), context)
            elif step_type == "set_value":
                value = step.get("value")
            elif step_type == "tool_call":
                value = self._execute_tool_call(step, context)
            elif step_type == "employee_task":
                value = self._execute_logic(
                    {"type": "employee_task", **step},
                    context,
                    user_id=user_id,
                ).get("employee_result")
            elif step_type in ("vibe_code", "vibe_workflow"):
                vibe_out = self._execute_logic(
                    {"type": step_type, **step},
                    context,
                    user_id=user_id,
                )
                value = vibe_out.get("vibe_run") or vibe_out.get("vibe_workflow_run") or vibe_out
            else:
                raise ValueError(f"不支持的 pipeline step 类型: {step_type}")
            outputs[output_var] = value
            context[output_var] = value
        return outputs

    def _execute_tool_call(self, step: Dict[str, Any], context: Dict[str, Any]) -> Any:
        tool = str(step.get("tool") or "")
        if tool == "echo":
            return resolve_value(
                step.get("args") or context, {"global": context, "result": context}
            )
        if tool == "extract_keys":
            return sorted(context.keys())
        raise ValueError(f"工具未在 ESkill allowlist 中: {tool}")

    def _passes_quality_gate(self, output: Dict[str, Any], gate: Dict[str, Any]) -> bool:
        return bool(self._quality_report(output, gate)["passed"])

    def _quality_report(self, output: Dict[str, Any], gate: Dict[str, Any]) -> Dict[str, Any]:
        issues: list[str] = []
        score = 1.0
        required_keys = [str(x) for x in (gate.get("required_keys") or [])]
        for key in required_keys:
            if key not in output:
                issues.append(f"missing_key:{key}")
        min_length = int(gate.get("min_length") or 0)
        text = " ".join(
            str(v)
            for k, v in output.items()
            if k not in {"logic_type", "eskill_logic_type", "solidified_version"}
        )
        if min_length > 0:
            if len(text) < min_length:
                issues.append(f"min_length:{len(text)}<{min_length}")
                score = min(score, len(text) / max(min_length, 1))
        contains_all = [str(x) for x in (gate.get("contains_all") or [])]
        for token in contains_all:
            if token and token not in text:
                issues.append(f"missing_text:{token}")
                score = min(score, 0.6)
        contains_any = [str(x) for x in (gate.get("contains_any") or [])]
        if contains_any and not any(token in text for token in contains_any):
            issues.append("missing_any_text")
            score = min(score, 0.7)
        regex = str(gate.get("regex") or "")
        if regex:
            try:
                if not re.search(regex, text):
                    issues.append("regex_not_matched")
                    score = min(score, 0.7)
            except re.error:
                issues.append("invalid_regex")
                score = min(score, 0.5)
        business_rules = gate.get("business_rules") or []
        if isinstance(business_rules, list):
            for rule in business_rules:
                if not isinstance(rule, dict):
                    continue
                key = str(rule.get("key") or "")
                if rule.get("op") == "not_empty" and not output.get(key):
                    issues.append(f"business_not_empty:{key}")
                    score = min(score, 0.6)
                if rule.get("op") == "equals" and output.get(key) != rule.get("value"):
                    issues.append(f"business_equals:{key}")
                    score = min(score, 0.6)
        min_score = float(gate.get("min_score") or 0.0)
        passed = not issues and score >= min_score
        return {"passed": passed, "score": round(score, 4), "issues": issues}

    def _apply_patch(self, logic: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        patched = deepcopy(logic)
        changes = patch.get("changes") if isinstance(patch, dict) else {}
        if not isinstance(changes, dict):
            return patched
        for key, value in changes.items():
            if key == "metadata":
                meta = dict(patched.get("metadata") or {})
                if isinstance(value, dict):
                    meta.update(value)
                else:
                    meta["value"] = value
                patched["metadata"] = meta
            else:
                patched[key] = value
        return patched

    def _is_within_domain(
        self,
        skill: ESkill,
        logic: Dict[str, Any],
        input_data: Dict[str, Any],
    ) -> bool:
        keywords = logic.get("domain_keywords") or logic.get("allowed_keywords") or []
        if isinstance(keywords, str):
            keywords = [x.strip() for x in re.split(r"[,，\s]+", keywords) if x.strip()]
        if not keywords:
            keywords = [x for x in re.split(r"[,，\s]+", skill.domain or "") if len(x) >= 2]
        if not keywords:
            return True
        text = json.dumps(input_data, ensure_ascii=False).lower()
        return any(str(keyword).lower() in text for keyword in keywords)

    def _retrieve_success_history(
        self,
        db: Session,
        skill_id: int,
        input_data: Dict[str, Any],
        *,
        limit: int = 5,
    ) -> list[Dict[str, Any]]:
        text = json.dumps(input_data, ensure_ascii=False).lower()
        rows = (
            db.query(ESkillRun)
            .filter(
                ESkillRun.eskill_id == skill_id,
                ESkillRun.stage.in_(["solidified", "dynamic"]),
                ESkillRun.error_message == "",
            )
            .order_by(ESkillRun.id.desc())
            .limit(30)
            .all()
        )
        matches: list[Dict[str, Any]] = []
        for row in rows:
            patch = _loads(row.patch_json, {})
            prior_input = _loads(row.input_json, {})
            prior_text = json.dumps(prior_input, ensure_ascii=False).lower()
            if not text or not prior_text or set(text.split()) & set(prior_text.split()):
                matches.append(patch)
            if len(matches) >= limit:
                break
        return matches

    def _rollback_to_previous_version(self, db: Session, skill: ESkill) -> bool:
        previous = (
            db.query(ESkillVersion)
            .filter(
                ESkillVersion.eskill_id == skill.id,
                ESkillVersion.version < int(skill.active_version or 0),
            )
            .order_by(ESkillVersion.version.desc())
            .first()
        )
        if not previous:
            return False
        skill.active_version = previous.version
        skill.updated_at = datetime.now(timezone.utc)
        db.add(skill)
        return True

    def _merge_overrides(self, logic: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(logic)
        for key, value in overrides.items():
            if value not in (None, ""):
                merged[key] = value
        return merged


default_eskill_runtime = ESkillRuntime()
