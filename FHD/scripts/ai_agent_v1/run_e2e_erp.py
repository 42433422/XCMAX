#!/usr/bin/env python3
"""AI Agent V1 端到端 — ERP：客户下单 → AI 自动审单 → 自动发货 → 通知 → Excel。

完整链路：
  1) 接收客户下单（自然语言或 Excel 导入）
  2) 解析订单 → AI 审单（业务规则）
  3) 写发货单 → 自动批准（低风险）or 人工审批（高金额）
  4) 标记发货 → 通知客户
  5) 导出当日 Excel

证据：docs/evidence/ai-agent-v1/e2e-erp-<stamp>.json
"""
from __future__ import annotations

import argparse
import json
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


def _build_erp_plan(plan_id: str) -> Any:
    from app.application.workflow.types import PlanGraph, WorkflowNode

    return PlanGraph(
        plan_id=plan_id,
        intent="erp_order_to_shipment",
        todo_steps=[
            "解析客户下单文本",
            "AI 审单（业务规则）",
            "写发货单",
            "标记发货",
            "微信通知客户",
            "导出当日 Excel",
        ],
        nodes=[
            WorkflowNode(
                node_id="parse_order",
                tool_id="order_parse",
                action="run",
                params={
                    "order_text": "上海宏达 9702-C 1000个 @12.5 / 北京天元 8801-A 500个 @25.0",
                },
                risk="low",
                idempotent=True,
            ),
            WorkflowNode(
                node_id="ai_audit",
                tool_id="audit_engine",
                action="check",
                params={"input_from": "parse_order", "rule_set": "v1_standard"},
                risk="low",
                depends_on=["parse_order"],
            ),
            WorkflowNode(
                node_id="ensure_customers",
                tool_id="customers",
                action="ensure_exists",
                params={"input_from": "parse_order.customers"},
                risk="medium",
                depends_on=["parse_order"],
            ),
            WorkflowNode(
                node_id="create_shipments",
                tool_id="shipment_generate",
                action="generate",
                params={"input_from": "parse_order.items"},
                risk="medium",
                depends_on=["ai_audit", "ensure_customers"],
            ),
            WorkflowNode(
                node_id="mark_shipped",
                tool_id="shipment_records",
                action="update",
                params={"input_from": "create_shipments", "status": "shipped"},
                risk="medium",
                depends_on=["create_shipments"],
            ),
            WorkflowNode(
                node_id="notify_customers",
                tool_id="wechat_send",
                action="send",
                params={"template": "shipped_notification", "input_from": "mark_shipped"},
                risk="medium",
                depends_on=["mark_shipped"],
            ),
            WorkflowNode(
                node_id="export_daily_excel",
                tool_id="excel_export",
                action="run",
                params={"report": "daily_shipment"},
                risk="low",
                idempotent=True,
                depends_on=["mark_shipped"],
            ),
        ],
        risk_level="medium",
    )


def _mock_e2e_dispatcher(
    tool_id: str, action: str, params: dict[str, Any]
) -> dict[str, Any]:
    if tool_id == "order_parse" and action == "run":
        return {
            "success": True,
            "customers": ["上海宏达", "北京天元"],
            "items": [
                {"customer": "上海宏达", "model_number": "9702-C", "quantity": 1000, "unit_price": 12.5},
                {"customer": "北京天元", "model_number": "8801-A", "quantity": 500, "unit_price": 25.0},
            ],
            "message": "mock: 解析 2 个客户 2 条商品",
        }
    if tool_id == "audit_engine" and action == "check":
        return {
            "success": True,
            "audit_decision": "auto_approve",
            "risk_score": 0.12,
            "anomalies": [],
            "message": "mock: AI 审单通过",
        }
    if tool_id == "customers" and action == "ensure_exists":
        units = params.get("input_from") or ["上海宏达", "北京天元"]
        return {
            "success": True,
            "data": [{"unit_name": u, "id": hash(u) % 10000} for u in units],
            "message": f"mock: {len(units)} 客户已确认",
        }
    if tool_id == "shipment_generate" and action == "generate":
        items = params.get("input_from") or []
        return {
            "success": True,
            "data": [
                {"order_number": f"ERP-{i+1:03d}", "amount": (it.get("quantity", 1) * it.get("unit_price", 0))}
                for i, it in enumerate(items)
            ],
            "message": f"mock: 已生成 {len(items)} 张发货单",
        }
    if tool_id == "shipment_records" and action == "update":
        return {
            "success": True,
            "updated": 2,
            "message": "mock: 2 张发货单标记为已发货",
        }
    if tool_id == "wechat_send" and action == "send":
        return {
            "success": True,
            "message_ids": ["wx-msg-001", "wx-msg-002"],
            "message": "mock: 2 条微信通知已发",
        }
    if tool_id == "excel_export" and action == "run":
        return {
            "success": True,
            "file_path": "/tmp/daily-shipment-20260605.xlsx",
            "rows": 32,
            "message": "mock: 当日发货 Excel 已导出",
        }
    return {"success": False, "message": f"mock 未实现: {tool_id}.{action}"}


def run_erp_e2e(strategy: str = "auto") -> dict[str, Any]:
    from app.application.workflow.approval_gated_engine import (
        ApprovalGatedEngine,
        build_gated_evidence,
    )
    from app.application.workflow.engine import WorkflowEngine

    _stub_planner_rag()
    engine = WorkflowEngine(tool_dispatcher=_mock_e2e_dispatcher)
    gated = ApprovalGatedEngine(engine=engine)

    plan_id = f"e2e-erp-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    plan = _build_erp_plan(plan_id)
    runtime_ctx: dict[str, Any] = {
        "user_id": "e2e_erp_demo",
        "message": "ERP 端到端：客户下单 → AI 审单 → 发货 → 通知 → Excel",
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
    evidence["e2e_scenario"] = "erp_order_to_shipment"

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = EVIDENCE_DIR / f"e2e-erp-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence["_evidence_path"] = str(out)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Agent V1 ERP 端到端 demo")
    parser.add_argument("--strategy", choices=["auto", "interactive", "reject"], default="auto")
    args = parser.parse_args(argv)

    _bootstrap()
    evidence = run_erp_e2e(strategy=args.strategy)
    decision = evidence.get("gated_decision") or {}
    print(
        f"e2e_erp strategy={evidence.get('approval_strategy')} "
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
