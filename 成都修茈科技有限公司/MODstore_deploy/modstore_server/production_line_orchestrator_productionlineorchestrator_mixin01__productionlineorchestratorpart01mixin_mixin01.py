# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.customer_issue_delivery_contract import execution_succeeded
import importlib
from copy import deepcopy


def _facade():
    return importlib.import_module("modstore_server.production_line_orchestrator")


class __ProductionLineOrchestratorPart01MixinPart01Mixin:
    def __init__(self):
        self._step_results: _facade().Dict[str, _facade().StepResult] = {}
        self._callbacks: _facade().Dict[str, _facade().Callable] = {}
        self._running = False
        self._step_contexts = {}

    def register_callback(self, event: str, callback: _facade().Callable) -> None:
        self._callbacks[event] = callback

    def _fire(self, event: str, **kwargs) -> _facade().Any:
        cb = self._callbacks.get(event)
        if cb:
            return cb(**kwargs)
        return None

    def get_step(self, step_id: str) -> _facade().Optional[_facade().FlowStep]:
        for s in _facade().ALL_STEPS:
            if s.step_id == step_id:
                return s
        return None

    def get_step_status(self, step_id: str) -> _facade().StepStatus:
        r = self._step_results.get(step_id)
        return r.status if r else _facade().StepStatus.PENDING

    def get_pipeline_status(self) -> _facade().Dict[str, _facade().Any]:
        lines = {}
        for name, steps in (
            ("production_line", _facade().PRODUCTION_LINE_STEPS),
            ("operations_line", _facade().OPERATIONS_LINE_STEPS),
        ):
            rows = []
            for step in steps:
                result = self._step_results.get(step.step_id)
                rows.append(
                    {
                        "step_id": step.step_id,
                        "name": step.name,
                        "status": result.status.value if result else "pending",
                        "executor": step.executor,
                        "approval_gate": step.approval_gate.value,
                        "sub_steps": step.sub_steps,
                        "cross_line_trigger": step.cross_line_trigger,
                        "error": result.error if result else None,
                        "evidence": (
                            (result.data.get("result") or {}).get("evidence") if result else None
                        ),
                    }
                )
            completed = sum(row["status"] == "completed" for row in rows)
            lines[name] = {
                "total": len(rows),
                "completed": completed,
                "steps": rows,
                "automation_rate": round(completed / len(rows) * 100, 1) if rows else 0,
            }
        total = sum(line["total"] for line in lines.values())
        completed = sum(line["completed"] for line in lines.values())
        return {
            **lines,
            "overall_automation_rate": round(completed / total * 100, 1) if total else 0,
        }

    async def run_step(
        self,
        step_id: str,
        context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    ) -> _facade().StepResult:
        step = self.get_step(step_id)
        if not step:
            return _facade().StepResult(
                step_id=step_id,
                status=_facade().StepStatus.FAILED,
                error="step not found",
            )
        self._step_results[step_id] = _facade().StepResult(
            step_id=step_id, status=_facade().StepStatus.RUNNING
        )
        self._fire("step_started", step_id=step_id, step_name=step.name, line=step.line.value)
        self._step_contexts[step_id] = deepcopy(context or {})
        attempts = step.max_retries + 1 if step.retry_on_failure else 1
        for attempt in range(attempts):
            try:
                output = await self._execute_step(step, deepcopy(context or {}))
                return await self._finish_step(step, {**(context or {}), **output}, context or {})
            except RECOVERABLE_ERRORS as exc:
                if attempt + 1 < attempts and step_id != "O7":
                    continue
                error = str(exc)
                self._step_results[step_id] = _facade().StepResult(
                    step_id=step_id, status=_facade().StepStatus.FAILED, error=error
                )
                self._fire("step_failed", step_id=step_id, step_name=step.name, error=error)
                if step_id == "O7":
                    from modstore_server.customer_issue_intake import record_dispatch_failure

                    record_dispatch_failure(dict(context or {}), error)
                return self._step_results[step_id]
        raise AssertionError("unreachable step attempt")

    async def _finish_step(self, step, data, context):
        result = data.get("result") or {}
        if not isinstance(result, dict):
            result = {}
        waiting = result.get("skipped") is True or result.get("status") in {
            "waiting_evidence",
            "pending",
            "unknown",
            "accepted",
            "dispatched",
        }
        failed = result.get("ok") is False and not waiting
        if step.step_id == "O7" and not context.get("business"):
            failed = not execution_succeeded(result)
        if waiting or failed:
            state = (
                _facade().StepStatus.WAITING_EVIDENCE if waiting else _facade().StepStatus.FAILED
            )
            error = str(
                result.get("reason") or result.get("error") or "business evidence unavailable"
            )
            self._step_results[step.step_id] = _facade().StepResult(
                step_id=step.step_id,
                status=state,
                data={**data, "context": dict(context)},
                error=error,
            )
            self._fire(
                "step_waiting_evidence" if waiting else "step_failed",
                step_id=step.step_id,
                step_name=step.name,
                error=error,
            )
            if failed and step.step_id == "O7" and not context.get("business"):
                from modstore_server.customer_issue_intake import record_dispatch_failure

                record_dispatch_failure(dict(context), error)
            return self._step_results[step.step_id]
        if step.approval_gate != _facade().ApprovalGate.NONE:
            state = _facade().StepStatus.AWAITING_APPROVAL
            self._fire(
                "step_awaiting_approval",
                step_id=step.step_id,
                step_name=step.name,
                gate=step.approval_gate.value,
            )
        else:
            state = _facade().StepStatus.COMPLETED
        self._step_results[step.step_id] = _facade().StepResult(
            step_id=step.step_id, status=state, data=data
        )
        if state != _facade().StepStatus.COMPLETED:
            return self._step_results[step.step_id]
        return await self._continue_step(step, data)

    async def _continue_step(self, step, data):
        self._fire("step_completed", step_id=step.step_id, step_name=step.name)
        if step.cross_line_trigger and not data.get("business"):
            # The evidence observer never turns a read into a new coding dispatch.
            cross_context = {
                key: value
                for key, value in data.items()
                if key not in {"from_step", "to_step", "result_data"}
            }
            self._fire(
                "cross_line_trigger",
                from_step=step.step_id,
                to_step=step.cross_line_trigger,
                **cross_context,
                result_data=data,
            )
        if step.auto_trigger_next and not getattr(self, "_release_train_subset", False):
            next_step = self._get_next_step(step)
            if next_step:
                return await self.run_step(next_step.step_id, context=data)
        return self._step_results[step.step_id]

    def _get_next_step(self, step: _facade().FlowStep) -> _facade().Optional[_facade().FlowStep]:
        if step.line == _facade().LineType.PRODUCTION:
            steps = _facade().PRODUCTION_LINE_STEPS
        else:
            steps = _facade().OPERATIONS_LINE_STEPS
        idx = next((i for (i, s) in enumerate(steps) if s.step_id == step.step_id), -1)
        if 0 <= idx < len(steps) - 1:
            return steps[idx + 1]
        return None

    async def _execute_step(
        self, step: _facade().FlowStep, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        from modstore_server.production_line_business import BUSINESS_STEPS, observe_business_step

        if step.step_id in BUSINESS_STEPS or (step.step_id == "O7" and context.get("business")):
            return observe_business_step(step.step_id, context)
        executor_map = {
            "P1": self._step_site_and_seo,
            "P2": self._step_ai_coding,
            "P3": self._step_auto_test,
            "P4": self._step_build_and_package,
            "P5": self._step_auto_release,
            "P6": self._step_push_updates,
            "P7": self._step_runtime_monitor,
            "P8": self._step_auto_purify,
            "P9": self._step_version_evolution,
            "P10": self._step_ai_self_driven,
            "O7": self._step_feedback,
        }
        fn = executor_map.get(step.step_id)
        if fn:
            return await fn(context)
        return {
            "step": step.step_id,
            "result": {
                "ok": False,
                "status": "waiting_evidence",
                "reason": "executor_not_integrated",
            },
        }

    async def approve_step(self, step_id: str, admin_user_id: int = 0) -> _facade().StepResult:
        step = self.get_step(step_id)
        if not step:
            return _facade().StepResult(
                step_id=step_id,
                status=_facade().StepStatus.FAILED,
                error="step not found",
            )
        current = self._step_results.get(step_id)
        if not current or current.status != _facade().StepStatus.AWAITING_APPROVAL:
            return _facade().StepResult(
                step_id=step_id,
                status=_facade().StepStatus.FAILED,
                error="step not awaiting approval",
            )
        if step_id.startswith("O"):
            # Approval authorizes progression; it cannot stand in for a source receipt.
            context = deepcopy(self._step_contexts.get(step_id) or {})
            output = await self._execute_step(step, context)
            if (output.get("result") or {}).get("status") != "completed":
                return await self._finish_step(step, {**context, **output}, context)
            if output.get("result") != current.data.get("result"):
                return await self._finish_step(step, {**context, **output}, context)
        self._step_results[step_id] = _facade().StepResult(
            step_id=step_id,
            status=_facade().StepStatus.COMPLETED,
            data=current.data,
            approval_id=admin_user_id or None,
        )
        self._fire(
            "step_approved", step_id=step_id, step_name=step.name, admin_user_id=admin_user_id
        )
        return await self._continue_step(step, current.data)

    async def reject_step(
        self, step_id: str, admin_user_id: int = 0, reason: str = ""
    ) -> _facade().StepResult:
        current = self._step_results.get(step_id)
        if not current or current.status != _facade().StepStatus.AWAITING_APPROVAL:
            return _facade().StepResult(
                step_id=step_id,
                status=_facade().StepStatus.FAILED,
                error="step not awaiting approval",
            )
        self._step_results[step_id] = _facade().StepResult(
            step_id=step_id,
            status=_facade().StepStatus.REJECTED,
            data=current.data,
            error=reason,
        )
        self._fire("step_rejected", step_id=step_id, admin_user_id=admin_user_id, reason=reason)
        return self._step_results[step_id]

    async def run_full_pipeline(self, line=None, start_from=None, context=None):
        line = line or _facade().LineType.PRODUCTION
        steps = (
            _facade().PRODUCTION_LINE_STEPS
            if line == _facade().LineType.PRODUCTION
            else _facade().OPERATIONS_LINE_STEPS
        )
        ids = [step.step_id for step in steps]
        if start_from is not None:
            if start_from not in ids:
                return {"ok": False, "error": "start step not found"}
            ids = ids[ids.index(start_from) :]
        return {**await self.run_pipeline_steps(ids, context=context), "line": line.value}

    async def run_pipeline_steps(self, step_ids, *, context=None):
        """One owner for iteration; run_step's direct-call chaining is suspended."""
        wanted = [str(s).strip().upper() for s in step_ids if str(s).strip()]
        if not wanted:
            return {"ok": True, "skipped": True, "reason": "empty step_ids"}
        if self._running:
            return {"ok": False, "error": "pipeline already running"}
        self._running = True
        previous_subset = getattr(self, "_release_train_subset", False)
        self._release_train_subset = True
        current_context, executed = dict(context or {}), []
        self._fire("pipeline_started", start_from=wanted[0])
        try:
            for step_id in wanted:
                if not self._running:
                    return {"ok": False, "stopped": True, "executed_steps": executed}
                result = await self.run_step(step_id, context=current_context)
                executed.append(step_id)
                if result.status != _facade().StepStatus.COMPLETED:
                    paused = result.status in {
                        _facade().StepStatus.AWAITING_APPROVAL,
                        _facade().StepStatus.WAITING_EVIDENCE,
                    }
                    self._fire(
                        "pipeline_paused" if paused else "pipeline_failed",
                        step_id=step_id,
                        reason=result.status.value,
                    )
                    return {
                        "ok": paused,
                        "paused": paused,
                        "paused_at_step" if paused else "failed_at_step": step_id,
                        "status": result.status.value,
                        "error": result.error,
                        "executed_steps": executed,
                        "pipeline_status": self.get_pipeline_status(),
                    }
                current_context = result.data
            self._fire("pipeline_completed")
            return {
                "ok": True,
                "paused": False,
                "executed_steps": executed,
                "pipeline_status": self.get_pipeline_status(),
            }
        finally:
            self._running = False
            self._release_train_subset = previous_subset

    def stop_pipeline(self) -> None:
        self._running = False
        self._fire("pipeline_stopped")

    def _skipped_step_result(
        self, step: _facade().FlowStep, message: str
    ) -> _facade().Dict[str, _facade().Any]:
        """静态步：由 CI/外部系统/admin 门控完成，编排器不 dispatch 员工。"""
        return {
            "step": step.step_id,
            "result": {
                "ok": False,
                "status": "waiting_evidence",
                "skipped": True,
                "executor": step.executor,
                "message": message,
            },
        }

    async def _step_site_and_seo(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "更新官网内容、SEO站点地图、robots.txt、营销站构建；确保所有页面可访问、SEO合规。",
            context,
            target_employee_id="site-content-editor",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "P1", "result": out}

    async def _step_ai_coding(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        from modstore_server.craft_executor import (
            CRAFT_PIPELINE_ORDER,
            CRAFT_STEP_EMPLOYEE_MAP,
            dispatch_craft_step,
        )

        results = {}
        for employee_id in CRAFT_PIPELINE_ORDER:
            step_id = next(
                (s for (s, e) in CRAFT_STEP_EMPLOYEE_MAP.items() if e == employee_id),
                employee_id,
            )
            try:
                r = await dispatch_craft_step(step_id, **context)
                results[employee_id] = r
            except RECOVERABLE_ERRORS as exc:
                _facade().logger.warning("craft step %s failed: %s", step_id, exc)
                results[employee_id] = {"ok": False, "error": str(exc)}
        fhd_out: _facade().Dict[str, _facade().Any] = {}
        try:
            from modstore_server.employee_orchestrator import plan_and_dispatch

            fhd_out = plan_and_dispatch(
                context.get("task_description")
                or "根据运营线反馈或遥测 backlog 修复 FHD app/ 并提交 PR。",
                context,
                target_employee_id="fhd-core-maintainer",
                created_by_user_id=int(context.get("created_by_user_id") or 0),
                include_dependencies=True,
            )
        except RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("fhd-core-maintainer dispatch failed: %s", exc)
            fhd_out = {"ok": False, "error": str(exc)}
        return {"step": "P2", "craft_results": results, "fhd_core": fhd_out}
