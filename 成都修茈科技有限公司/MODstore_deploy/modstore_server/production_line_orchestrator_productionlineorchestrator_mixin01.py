# ruff: noqa
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.production_line_orchestrator")


class _ProductionLineOrchestratorPart01Mixin:

    def __init__(self):
        self._step_results: _facade().Dict[str, _facade().StepResult] = {}
        self._callbacks: _facade().Dict[str, _facade().Callable] = {}
        self._running = False

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
        production_steps = []
        for s in _facade().PRODUCTION_LINE_STEPS:
            r = self._step_results.get(s.step_id)
            production_steps.append(
                {
                    "step_id": s.step_id,
                    "name": s.name,
                    "status": r.status.value if r else "pending",
                    "executor": s.executor,
                    "approval_gate": s.approval_gate.value,
                    "sub_steps": s.sub_steps,
                    "cross_line_trigger": s.cross_line_trigger,
                }
            )
        operations_steps = []
        for s in _facade().OPERATIONS_LINE_STEPS:
            r = self._step_results.get(s.step_id)
            operations_steps.append(
                {
                    "step_id": s.step_id,
                    "name": s.name,
                    "status": r.status.value if r else "pending",
                    "executor": s.executor,
                    "approval_gate": s.approval_gate.value,
                    "sub_steps": s.sub_steps,
                    "cross_line_trigger": s.cross_line_trigger,
                }
            )
        p_completed = sum((1 for s in production_steps if s["status"] == "completed"))
        o_completed = sum((1 for s in operations_steps if s["status"] == "completed"))
        return {
            "production_line": {
                "total": len(_facade().PRODUCTION_LINE_STEPS),
                "completed": p_completed,
                "automation_rate": round(
                    p_completed / len(_facade().PRODUCTION_LINE_STEPS) * 100, 1
                ),
                "steps": production_steps,
            },
            "operations_line": {
                "total": len(_facade().OPERATIONS_LINE_STEPS),
                "completed": o_completed,
                "automation_rate": round(
                    o_completed / len(_facade().OPERATIONS_LINE_STEPS) * 100, 1
                ),
                "steps": operations_steps,
            },
            "overall_automation_rate": round(
                (p_completed + o_completed)
                / (len(_facade().PRODUCTION_LINE_STEPS) + len(_facade().OPERATIONS_LINE_STEPS))
                * 100,
                1,
            ),
        }

    async def run_step(
        self, step_id: str, context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    ) -> _facade().StepResult:
        step = self.get_step(step_id)
        if not step:
            return _facade().StepResult(
                step_id=step_id, status=_facade().StepStatus.FAILED, error="step not found"
            )
        self._step_results[step_id] = _facade().StepResult(
            step_id=step_id, status=_facade().StepStatus.RUNNING
        )
        self._fire("step_started", step_id=step_id, step_name=step.name, line=step.line.value)
        try:
            result_data = await self._execute_step(step, context or {})
            if step.approval_gate != _facade().ApprovalGate.NONE:
                self._step_results[step_id] = _facade().StepResult(
                    step_id=step_id, status=_facade().StepStatus.AWAITING_APPROVAL, data=result_data
                )
                self._fire(
                    "step_awaiting_approval",
                    step_id=step_id,
                    step_name=step.name,
                    gate=step.approval_gate.value,
                )
                return self._step_results[step_id]
            self._step_results[step_id] = _facade().StepResult(
                step_id=step_id, status=_facade().StepStatus.COMPLETED, data=result_data
            )
            self._fire("step_completed", step_id=step_id, step_name=step.name)
            if step.cross_line_trigger:
                self._fire("cross_line_trigger", from_step=step_id, to_step=step.cross_line_trigger)
            if step.auto_trigger_next and (not getattr(self, "_release_train_subset", False)):
                next_step = self._get_next_step(step)
                if next_step:
                    return await self.run_step(next_step.step_id, context=result_data)
            return self._step_results[step_id]
        except Exception as exc:
            _facade().logger.exception("pipeline step %s failed: %s", step_id, exc)
            self._step_results[step_id] = _facade().StepResult(
                step_id=step_id, status=_facade().StepStatus.FAILED, error=str(exc)
            )
            self._fire("step_failed", step_id=step_id, step_name=step.name, error=str(exc))
            if step.retry_on_failure and step.max_retries > 0:
                return await self._retry_step(step, context, remaining=step.max_retries)
            return self._step_results[step_id]

    def _get_next_step(self, step: _facade().FlowStep) -> _facade().Optional[_facade().FlowStep]:
        if step.line == _facade().LineType.PRODUCTION:
            steps = _facade().PRODUCTION_LINE_STEPS
        else:
            steps = _facade().OPERATIONS_LINE_STEPS
        idx = next((i for (i, s) in enumerate(steps) if s.step_id == step.step_id), -1)
        if 0 <= idx < len(steps) - 1:
            return steps[idx + 1]
        return None

    async def _retry_step(
        self, step: _facade().FlowStep, context: _facade().Optional[_facade().Dict], remaining: int
    ) -> _facade().StepResult:
        _facade().logger.info(
            "retrying step %s (%s), remaining=%d", step.step_id, step.name, remaining
        )
        try:
            result_data = await self._execute_step(step, context or {})
            self._step_results[step.step_id] = _facade().StepResult(
                step_id=step.step_id, status=_facade().StepStatus.COMPLETED, data=result_data
            )
            self._fire("step_completed", step_id=step.step_id, step_name=step.name)
            return self._step_results[step.step_id]
        except Exception as exc:
            if remaining > 1:
                return await self._retry_step(step, context, remaining - 1)
            self._step_results[step.step_id] = _facade().StepResult(
                step_id=step.step_id, status=_facade().StepStatus.FAILED, error=str(exc)
            )
            self._fire("step_failed", step_id=step.step_id, step_name=step.name, error=str(exc))
            return self._step_results[step.step_id]

    async def _execute_step(
        self, step: _facade().FlowStep, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
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
            "O1": self._step_acquisition,
            "O2": self._step_crm,
            "O3": self._step_quotation,
            "O4": self._step_payment,
            "O5": self._step_delivery,
            "O6": self._step_usage,
            "O7": self._step_feedback,
            "O8": self._step_acceptance,
            "O9": self._step_documents,
            "O10": self._step_reconciliation,
        }
        fn = executor_map.get(step.step_id)
        if fn:
            return await fn(context)
        return {"step": step.step_id, "result": {"ok": True, "message": f"{step.name} executed"}}

    async def approve_step(self, step_id: str, admin_user_id: int = 0) -> _facade().StepResult:
        step = self.get_step(step_id)
        if not step:
            return _facade().StepResult(
                step_id=step_id, status=_facade().StepStatus.FAILED, error="step not found"
            )
        current = self._step_results.get(step_id)
        if not current or current.status != _facade().StepStatus.AWAITING_APPROVAL:
            return _facade().StepResult(
                step_id=step_id,
                status=_facade().StepStatus.FAILED,
                error="step not awaiting approval",
            )
        self._step_results[step_id] = _facade().StepResult(
            step_id=step_id,
            status=_facade().StepStatus.APPROVED,
            data=current.data,
            approval_id=admin_user_id or None,
        )
        self._fire(
            "step_approved", step_id=step_id, step_name=step.name, admin_user_id=admin_user_id
        )
        self._step_results[step_id] = _facade().StepResult(
            step_id=step_id, status=_facade().StepStatus.COMPLETED, data=current.data
        )
        self._fire("step_completed", step_id=step_id, step_name=step.name)
        if step.cross_line_trigger:
            self._fire("cross_line_trigger", from_step=step_id, to_step=step.cross_line_trigger)
        if step.auto_trigger_next and (not getattr(self, "_release_train_subset", False)):
            next_step = self._get_next_step(step)
            if next_step:
                return await self.run_step(next_step.step_id, context=current.data)
        return self._step_results[step_id]

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
            step_id=step_id, status=_facade().StepStatus.REJECTED, data=current.data, error=reason
        )
        self._fire("step_rejected", step_id=step_id, admin_user_id=admin_user_id, reason=reason)
        return self._step_results[step_id]

    async def run_full_pipeline(
        self,
        line: _facade().LineType = _facade().LineType.PRODUCTION,
        start_from: _facade().Optional[str] = None,
        context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    ) -> _facade().Dict[str, _facade().Any]:
        self._running = True
        steps = (
            _facade().PRODUCTION_LINE_STEPS
            if line == _facade().LineType.PRODUCTION
            else _facade().OPERATIONS_LINE_STEPS
        )
        self._fire("pipeline_started", line=line.value, start_from=start_from)
        current_context = context or {}
        if current_context.get("release_train_subset"):
            self._release_train_subset = True
        started = start_from is None
        for step in steps:
            if not started:
                if step.step_id == start_from:
                    started = True
                else:
                    continue
            if not self._running:
                break
            result = await self.run_step(step.step_id, context=current_context)
            if result.status == _facade().StepStatus.AWAITING_APPROVAL:
                self._fire("pipeline_paused", step_id=step.step_id, reason="awaiting approval")
                return {
                    "ok": True,
                    "paused": True,
                    "paused_at_step": step.step_id,
                    "paused_at_name": step.name,
                    "line": line.value,
                    "message": f"步骤 {step.step_id}({step.name}) 等待审批后继续",
                    "pipeline_status": self.get_pipeline_status(),
                }
            if result.status == _facade().StepStatus.FAILED:
                self._fire("pipeline_failed", step_id=step.step_id, error=result.error)
                return {
                    "ok": False,
                    "failed_at_step": step.step_id,
                    "failed_at_name": step.name,
                    "line": line.value,
                    "error": result.error,
                    "pipeline_status": self.get_pipeline_status(),
                }
            current_context = result.data
        self._running = False
        self._fire("pipeline_completed", line=line.value)
        return {
            "ok": True,
            "paused": False,
            "line": line.value,
            "message": f"{('制作线' if line == _facade().LineType.PRODUCTION else '运营线')}全流程完成",
            "pipeline_status": self.get_pipeline_status(),
        }

    async def run_pipeline_steps(
        self,
        step_ids: _facade().Sequence[str],
        *,
        context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    ) -> _facade().Dict[str, _facade().Any]:
        """按给定 step_id 列表顺序执行（用于 digest release_train Phase C 子集）。"""
        wanted = [str(s).strip().upper() for s in step_ids if str(s).strip()]
        if not wanted:
            return {"ok": True, "skipped": True, "reason": "empty step_ids"}
        self._running = True
        self._fire(
            "pipeline_started", line=_facade().LineType.PRODUCTION.value, start_from=wanted[0]
        )
        current_context = context or {}
        if current_context.get("release_train_subset"):
            self._release_train_subset = True
        executed: _facade().List[str] = []
        for step_id in wanted:
            if not self._running:
                break
            result = await self.run_step(step_id, context=current_context)
            executed.append(step_id)
            if result.status == _facade().StepStatus.AWAITING_APPROVAL:
                self._fire("pipeline_paused", step_id=step_id, reason="awaiting approval")
                return {
                    "ok": True,
                    "paused": True,
                    "paused_at_step": step_id,
                    "executed_steps": executed,
                    "pipeline_status": self.get_pipeline_status(),
                }
            if result.status == _facade().StepStatus.FAILED:
                self._fire("pipeline_failed", step_id=step_id, error=result.error)
                return {
                    "ok": False,
                    "failed_at_step": step_id,
                    "executed_steps": executed,
                    "error": result.error,
                    "pipeline_status": self.get_pipeline_status(),
                }
            current_context = result.data
        self._running = False
        self._fire("pipeline_completed", line=_facade().LineType.PRODUCTION.value)
        return {
            "ok": True,
            "paused": False,
            "executed_steps": executed,
            "pipeline_status": self.get_pipeline_status(),
        }

    def stop_pipeline(self) -> None:
        self._running = False
        self._fire("pipeline_stopped")

    def _skipped_step_result(
        self, step: _facade().FlowStep, message: str
    ) -> _facade().Dict[str, _facade().Any]:
        """静态步：由 CI/外部系统/admin 门控完成，编排器不 dispatch 员工。"""
        return {
            "step": step.step_id,
            "result": {"ok": True, "skipped": True, "executor": step.executor, "message": message},
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
                (s for (s, e) in CRAFT_STEP_EMPLOYEE_MAP.items() if e == employee_id), employee_id
            )
            try:
                r = await dispatch_craft_step(step_id, **context)
                results[employee_id] = r
            except Exception as exc:
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
        except Exception as exc:
            _facade().logger.warning("fhd-core-maintainer dispatch failed: %s", exc)
            fhd_out = {"ok": False, "error": str(exc)}
        return {"step": "P2", "craft_results": results, "fhd_core": fhd_out}

    async def _step_auto_test(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "运行全站测试套件：pytest+vitest+Playwright E2E+覆盖率门禁；报告失败项并尝试自动修复。",
            context,
            target_employee_id="test-qa-runner",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "P3", "result": out}

    async def _step_build_and_package(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        step = self.get_step("P4")
        assert step
        return self._skipped_step_result(step, "构建打包已由 CI 工作流自动完成")

    async def _step_auto_release(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        strategy = _facade().os.environ.get("XCAGI_DEPLOY_STRATEGY", "canary").strip().lower()
        out = plan_and_dispatch(
            f"执行自动发布：GitHub Release+更新元数据+{strategy}策略部署到K8s；先部署到staging验证，再推进到production。",
            context,
            target_employee_id="deploy-release-officer",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "P5", "result": out, "strategy": strategy}

    async def _step_push_updates(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "推送更新：生成electron-updater元数据+Ed25519签名+Mod索引更新+上传发布SKU。",
            context,
            target_employee_id="push-update-context-officer",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "P6", "result": out}

    async def _step_runtime_monitor(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "运行时监控：采集日志+异常检测+告警摘要+熔断状态检查；发现问题触发自动修复。",
            context,
            target_employee_id="log-monitor-incident",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "P7", "result": out}

    async def _step_auto_purify(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "自动净化：CVE扫描+依赖更新+技术债清理+过期文件清理+安全审计；低风险自动修复，高风险提交审批。",
            context,
            target_employee_id="daily-orchestrator",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "P8", "result": out}

    async def _step_version_evolution(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        from modstore_server.auto_version_bump import auto_version_bump
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = str(repo_root())
        out = auto_version_bump(root)
        return {"step": "P9", "result": out}

    async def _step_ai_self_driven(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        from modstore_server.telemetry_backlog_loop import run_telemetry_scan

        out = run_telemetry_scan()
        return {"step": "P10", "result": out}

    async def _step_acquisition(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        step = self.get_step("O1")
        assert step
        return self._skipped_step_result(step, "获客引流由官网与 SEO 流水线自动完成")

    async def _step_crm(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        import os
        import httpx

        health: _facade().Dict[str, _facade().Any] = {}
        fhd = (os.environ.get("XCAGI_FHD_INTERNAL_URL") or "").rstrip("/")
        if fhd:
            try:
                resp = httpx.get(f"{fhd}/api/operations-line/health", timeout=10.0)
                if resp.status_code < 400:
                    payload = resp.json()
                    health = payload.get("data") if isinstance(payload, dict) else {}
            except Exception:
                pass
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "处理客户需求：AI客服对话+工单分类+需求结构化→待派发队列。",
            context,
            target_employee_id="user-customer-service-officer",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "O2", "result": out, "operations_health": health}

    async def _step_quotation(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        step = self.get_step("O3")
        assert step
        return self._skipped_step_result(step, "报价与合同在 admin 审批门控后由业务系统完成")

    async def _step_payment(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        step = self.get_step("O4")
        assert step
        return self._skipped_step_result(
            step, "收费由支付系统（PostgreSQL SoT）自动处理，需 admin 审批"
        )

    async def _step_delivery(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        step = self.get_step("O5")
        assert step
        return self._skipped_step_result(step, "软件交付由 CI/CD 与 K8s 发布流水线自动完成")

    async def _step_usage(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        step = self.get_step("O6")
        assert step
        return self._skipped_step_result(step, "用户使用由 FHD 运行时与 NeuroBus 自动处理")

    async def _step_feedback(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "处理用户反馈：审批流+变更请求+OPS_CLOSURE值班派发→交叉驱动制作线。",
            context,
            target_employee_id="change-request-auditor",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "O7", "result": out}

    async def _step_acceptance(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        step = self.get_step("O8")
        assert step
        return self._skipped_step_result(step, "交付确认由 QA 验收与 CI 门控完成")

    async def _step_documents(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        step = self.get_step("O9")
        assert step
        return self._skipped_step_result(step, "单据处理在 admin 审批后由模板引擎完成")

    async def _step_reconciliation(
        self, context: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        import os
        import httpx

        step = self.get_step("O10")
        assert step
        fhd = (
            os.environ.get("XCAGI_FHD_INTERNAL_URL") or os.environ.get("FHD_INTERNAL_URL") or ""
        ).rstrip("/")
        auto = (os.environ.get("RECONCILIATION_AUTO_CONFIRM") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if fhd and auto:
            try:
                resp = httpx.post(
                    f"{fhd}/api/operations-line/reconciliation/run",
                    params={"dry_run": "false"},
                    timeout=120.0,
                )
                if resp.status_code < 400:
                    payload = (
                        resp.json()
                        if resp.headers.get("content-type", "").startswith("application/json")
                        else {}
                    )
                    inner = payload.get("data") if isinstance(payload, dict) else {}
                    return {"step": "O10", "result": inner or payload, "auto_reconciliation": True}
            except Exception as exc:
                return {
                    "step": "O10",
                    "result": {"ok": False, "error": str(exc)[:300]},
                    "auto_reconciliation": False,
                }
        note = "已配置全自动对账时请设置 RECONCILIATION_AUTO_CONFIRM=1 与 XCAGI_FHD_INTERNAL_URL；否则在 admin 确认 draft 报告或 POST /api/operations-line/reconciliation/run"
        return self._skipped_step_result(step, note)
