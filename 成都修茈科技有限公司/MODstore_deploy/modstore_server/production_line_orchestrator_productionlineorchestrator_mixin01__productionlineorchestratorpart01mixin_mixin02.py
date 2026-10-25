# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.production_line_orchestrator")


class __ProductionLineOrchestratorPart01MixinPart02Mixin:
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
            except RECOVERABLE_ERRORS:
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
                    return {
                        "step": "O10",
                        "result": inner or payload,
                        "auto_reconciliation": True,
                    }
            except RECOVERABLE_ERRORS as exc:
                return {
                    "step": "O10",
                    "result": {"ok": False, "error": str(exc)[:300]},
                    "auto_reconciliation": False,
                }
        note = "已配置全自动对账时请设置 RECONCILIATION_AUTO_CONFIRM=1 与 XCAGI_FHD_INTERNAL_URL；否则在 admin 确认 draft 报告或 POST /api/operations-line/reconciliation/run"
        return self._skipped_step_result(step, note)
