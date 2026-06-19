#!/usr/bin/env python3
"""AI Agent V1 端到端 — Mod 商店：识别异常 → 自动发通知 → 出月报。

完整链路：
  1) 拉取最近 24h Mod 订单
  2) 识别异常订单（高金额、退款、重复）
  3) AI 员工起草通知
  4) 通过微信发送给商务
  5) 生成月报 Excel

证据：docs/evidence/ai-agent-v1/e2e-modstore-<stamp>.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = ROOT / "docs" / "evidence" / "ai-agent-v1"


def _bootstrap() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass


def _stub_planner_rag() -> None:
    import app.application as app_pkg
    import app.application.user_memory_vector_app_service as rag_mod

    class _Stub:
        def query(self, **_kwargs: Any) -> dict[str, Any]:
            return {"hits": []}

        def format_for_prompt(self, **_kwargs: Any) -> str:
            return ""

    def _factory() -> _Stub:
        return _Stub()

    rag_mod.get_user_memory_rag_app_service = _factory  # type: ignore[method-assign]
    app_pkg.get_user_memory_rag_app_service = _factory  # type: ignore[attr-defined]


def _build_modstore_plan(plan_id: str) -> Any:
    from app.application.workflow.types import PlanGraph, WorkflowNode

    return PlanGraph(
        plan_id=plan_id,
        intent="modstore_anomaly_notify_and_report",
        todo_steps=[
            "拉取最近 24h Mod 订单",
            "识别异常订单（金额 / 退款 / 重复）",
            "查询商务微信联系人",
            "生成通知 + 月报",
        ],
        nodes=[
            WorkflowNode(
                node_id="query_recent_orders",
                tool_id="modstore_orders",
                action="query",
                params={"date_from": "2026-06-04", "date_to": "2026-06-05", "limit": 100},
                risk="low",
                idempotent=True,
            ),
            WorkflowNode(
                node_id="identify_anomalies",
                tool_id="data_transform",
                action="execute",
                params={
                    "input_from": "query_recent_orders",
                    "condition": {"op": "gt", "field": "amount", "value": 100.0},
                },
                risk="low",
                depends_on=["query_recent_orders"],
            ),
            WorkflowNode(
                node_id="draft_notification",
                tool_id="ai_draft",
                action="compose",
                params={
                    "template": "modstore_anomaly_alert",
                    "input_from": "identify_anomalies",
                },
                risk="medium",
                depends_on=["identify_anomalies"],
            ),
            WorkflowNode(
                node_id="send_to_business",
                tool_id="wechat_send",
                action="send",
                params={
                    "contact_role": "business_manager",
                    "content_from": "draft_notification",
                },
                risk="medium",
                depends_on=["draft_notification"],
            ),
            WorkflowNode(
                node_id="generate_monthly_report",
                tool_id="excel_export",
                action="run",
                params={"report": "modstore_monthly", "date_from": "2026-06-01"},
                risk="low",
                idempotent=True,
            ),
        ],
        risk_level="medium",
    )


def _mock_e2e_dispatcher(
    tool_id: str, action: str, params: dict[str, Any]
) -> dict[str, Any]:
    """端到端 demo 工具桩。"""
    if (tool_id, action) == ("modstore_orders", "query"):
        return {
            "success": True,
            "data": [
                {"order_no": "MOD-001", "amount": 9.9, "status": "paid"},
                {"order_no": "MOD-002", "amount": 199.0, "status": "paid"},
                {"order_no": "MOD-003", "amount": 499.0, "status": "refunded"},
                {"order_no": "MOD-004", "amount": 999.0, "status": "paid"},
            ],
            "message": "mock: 4 条订单",
        }
    if tool_id == "data_transform":
        return {
            "success": True,
            "data": [
                {"order_no": "MOD-002", "amount": 199.0, "anomaly_type": "high_amount"},
                {"order_no": "MOD-003", "amount": 499.0, "anomaly_type": "refunded"},
                {"order_no": "MOD-004", "amount": 999.0, "anomaly_type": "high_amount"},
            ],
            "message": "mock: 3 条异常",
        }
    if (tool_id, action) == ("ai_draft", "compose"):
        return {
            "success": True,
            "content": "[异常告警] 24h 内 3 笔异常订单：MOD-002/MOD-003/MOD-004，建议商务跟进。",
            "message": "mock: 通知已起草",
        }
    if (tool_id, action) == ("wechat_send", "send"):
        return {
            "success": True,
            "message_id": "wx-mock-msg-001",
            "message": "mock: 微信通知已发送",
        }
    if (tool_id, action) == ("excel_export", "run"):
        return {
            "success": True,
            "file_path": "/tmp/modstore-monthly-202606.xlsx",
            "rows": 28,
            "message": "mock: 月报已生成",
        }
    return {"success": False, "message": f"mock 未实现: {tool_id}.{action}"}


def _dispatch_workflow_tool(
    tool_id: str, action: str, params: dict[str, Any]
) -> dict[str, Any]:
    from app.application.facades.tools_facade import execute_registered_workflow_tool
    return execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)


def run_modstore_e2e(strategy: str = "auto") -> dict[str, Any]:
    from app.application.workflow.approval_gated_engine import (
        ApprovalGatedEngine,
        build_gated_evidence,
    )
    from app.application.workflow.engine import WorkflowEngine

    _stub_planner_rag()
    dispatcher = _mock_e2e_dispatcher
    engine = WorkflowEngine(tool_dispatcher=dispatcher)
    gated = ApprovalGatedEngine(engine=engine)

    plan_id = f"e2e-modstore-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    plan = _build_modstore_plan(plan_id)
    runtime_ctx: dict[str, Any] = {
        "user_id": "e2e_modstore_demo",
        "message": "Mod 商店 24h 异常订单识别与通知",
    }

    decision, run_result = gated.run(plan=plan, runtime_context=runtime_ctx, strategy=strategy)
    evidence = build_gated_evidence(
        input_message=runtime_ctx["message"],
        plan=plan,
        decision=decision,
        run_result=run_result,
        execution_mode="mock",
        strategy=strategy,
    )
    evidence["e2e_scenario"] = "modstore_anomaly_notify_and_report"

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = EVIDENCE_DIR / f"e2e-modstore-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence["_evidence_path"] = str(out)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Agent V1 Mod 商店端到端 demo")
    parser.add_argument("--strategy", choices=["auto", "interactive", "reject"], default="auto")
    args = parser.parse_args(argv)

    _bootstrap()
    evidence = run_modstore_e2e(strategy=args.strategy)
    decision = evidence.get("gated_decision") or {}
    print(
        f"e2e_modstore strategy={evidence.get('approval_strategy')} "
        f"success={evidence.get('success')} plan_id={evidence.get('plan_id')}"
    )
    print(
        f"  approved={decision.get('all_approved')} pending={decision.get('pending_approval')} "
        f"rejected={decision.get('any_rejected')}"
    )
    for nr in (evidence.get("node_results_summary") or []):
        print(f"  {nr.get('node_id')}: success={nr.get('success')} action={nr.get('action')}")
    print(f"  evidence: {evidence.get('_evidence_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
