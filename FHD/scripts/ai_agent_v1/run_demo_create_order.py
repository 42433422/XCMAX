#!/usr/bin/env python3
"""AI Agent V1 — 写链路 demo：创建客户+订单+审批门控。

三种策略（由 --strategy 控制）:
  - auto        : 自动批准（CLI/CI 演示用），完整执行 plan
  - interactive : 挂起审批（生产用），生成 approval_request 工单但不执行
  - reject      : 自动拒绝（演示拒绝路径），生成工单但拒绝

证据写入 ``docs/evidence/ai-agent-v1/create-order-YYYYMMDD.json``。

示例（在 FHD 根目录）::

    python3 scripts/ai_agent_v1/run_demo_create_order.py --strategy auto
    python3 scripts/ai_agent_v1/run_demo_create_order.py --strategy interactive
    python3 scripts/ai_agent_v1/run_demo_create_order.py --strategy reject
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
DEFAULT_MESSAGE = "给客户上海宏达公司创建一张订单：1000 个 9702-C 型号，单价 12.5"
DEFAULT_USER_ID = "ai_agent_v1_demo"


def _bootstrap() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass


def _stub_planner_rag() -> None:
    """V0 同款 stub，避免 demo CLI 强依赖 PG 向量库。"""
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


def _dispatch_workflow_tool(
    tool_id: str, action: str, params: dict[str, Any]
) -> dict[str, Any]:
    from app.routes.tools import execute_registered_workflow_tool

    return execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)


def _database_reachable() -> bool:
    url = str(os.getenv("DATABASE_URL") or "").strip()
    if not url or url.startswith("sqlite"):
        return bool(url)
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _mock_tool_dispatcher(
    tool_id: str, action: str, params: dict[str, Any]
) -> dict[str, Any]:
    """无 DB 时的工具桩：仍经 WorkflowEngine 调度。"""
    if tool_id == "customers" and action == "ensure_exists":
        unit = str(params.get("unit_name") or "上海宏达公司").strip() or "上海宏达公司"
        return {
            "success": True,
            "id": 1001,
            "customer_name": unit,
            "unit_name": unit,
            "created": False,
            "message": f"mock: 单位已存在 {unit}",
        }
    if tool_id == "shipment_generate" and action == "generate":
        return {
            "success": True,
            "id": 5001,
            "order_number": "MOCK-20260605-001",
            "message": "mock: 发货单已生成",
        }
    return {"success": False, "message": f"mock 未实现: {tool_id}.{action}"}


def _build_create_order_plan(
    plan_id: str, message: str, params: dict[str, Any]
) -> Any:
    """
    手工构造 1 张写链路 PlanGraph（不依赖 LLM，确保 demo 稳定可重复）。

    PlanGraph:
      n1 customers.ensure_exists (medium)        — 创建/确认客户
      n2 shipment_generate.generate (medium)     — 生成发货单
    """
    from app.application.workflow.types import PlanGraph, WorkflowNode

    unit_name = str(params.get("unit_name") or "上海宏达公司").strip()
    products = params.get("products") or [
        {"model_number": "9702-C", "quantity": 1000, "unit_price": 12.5}
    ]

    return PlanGraph(
        plan_id=plan_id,
        intent="create_order_for_unit",
        todo_steps=[
            "意图分析：识别为创建订单任务",
            f"确保客户存在：{unit_name}",
            "生成发货单（写操作）",
            "返回执行明细",
        ],
        nodes=[
            WorkflowNode(
                node_id="ensure_customer",
                tool_id="customers",
                action="ensure_exists",
                params={"unit_name": unit_name},
                risk="medium",
                idempotent=True,
                description=f"确保客户 {unit_name} 存在",
            ),
            WorkflowNode(
                node_id="generate_shipment",
                tool_id="shipment_generate",
                action="generate",
                params={"unit_name": unit_name, "products": products},
                risk="medium",
                idempotent=False,
                depends_on=["ensure_customer"],
                description="生成发货单",
            ),
        ],
        risk_level="medium",
        metadata={"planner": "demo_v1", "message": message, "scenario": "create_order"},
    )


def _default_output_path(tag: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return EVIDENCE_DIR / f"create-order-{tag}-{stamp}.json"


def run_create_order_demo(
    message: str,
    *,
    strategy: str,
    user_id: str = DEFAULT_USER_ID,
    output_path: Path | None = None,
) -> dict[str, Any]:
    from app.application.workflow.approval_gated_engine import (
        ApprovalGatedEngine,
        build_gated_evidence,
    )
    from app.application.workflow.engine import WorkflowEngine

    _stub_planner_rag()

    force_live = str(os.environ.get("AI_AGENT_V1_LIVE_TOOLS", "")).strip().lower() in {
        "1", "true", "yes",
    }
    force_mock = str(os.environ.get("AI_AGENT_V1_MOCK_TOOLS", "")).strip().lower() in {
        "1", "true", "yes",
    }
    if force_mock:
        dispatcher = _mock_tool_dispatcher
        execution_mode = "mock"
    elif force_live or _database_reachable():
        dispatcher = _dispatch_workflow_tool
        execution_mode = "live"
    else:
        dispatcher = _mock_tool_dispatcher
        execution_mode = "mock"

    engine = WorkflowEngine(tool_dispatcher=dispatcher)
    gated = ApprovalGatedEngine(engine=engine)

    plan_id = f"v1-create-order-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    plan = _build_create_order_plan(plan_id, message, params={})

    runtime_ctx: dict[str, Any] = {"user_id": user_id, "message": message}

    decision, run_result = gated.run(
        plan=plan, runtime_context=runtime_ctx, strategy=strategy
    )

    evidence = build_gated_evidence(
        input_message=message,
        plan=plan,
        decision=decision,
        run_result=run_result,
        execution_mode=execution_mode,
        strategy=strategy,
    )

    out = output_path or _default_output_path(strategy)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence["_evidence_path"] = str(out)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Agent V1 写链路 demo：创建客户+订单+审批")
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="用户自然语言输入")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID, help="demo 用户 ID")
    parser.add_argument(
        "--strategy",
        choices=["auto", "interactive", "reject"],
        default="auto",
        help="审批策略：auto 自动批准 / interactive 挂起等审批 / reject 自动拒绝",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="证据 JSON 路径（默认 docs/evidence/ai-agent-v1/create-order-<strategy>-<stamp>.json）",
    )
    args = parser.parse_args(argv)

    _bootstrap()
    evidence = run_create_order_demo(
        str(args.message or DEFAULT_MESSAGE).strip() or DEFAULT_MESSAGE,
        strategy=str(args.strategy),
        user_id=str(args.user_id or DEFAULT_USER_ID),
        output_path=args.output,
    )

    path = evidence.pop("_evidence_path", "")
    decision = evidence.get("gated_decision") or {}
    nodes = decision.get("node_decisions") or []
    print(
        f"strategy={evidence.get('approval_strategy')} success={evidence.get('success')} "
        f"plan_id={evidence.get('plan_id')}"
    )
    print(
        f"approval_requests={len(evidence.get('approval_request_ids') or [])} "
        f"approved={decision.get('all_approved')} pending={decision.get('pending_approval')} "
        f"rejected={decision.get('any_rejected')}"
    )
    for nd in nodes:
        flag = "✓" if nd.get("approved") else ("✗" if nd.get("rejected") else "⏳")
        print(
            f"  {flag} {nd.get('node_id')}: {nd.get('tool_id')}.{nd.get('action')} "
            f"risk={nd.get('risk')} reason={nd.get('reason')}"
        )
    if path:
        print(f"evidence: {path}")

    # 退出码：auto 期望 0（执行成功）；interactive/reject 期望 0（演示到达预期分支）
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
