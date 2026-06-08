#!/usr/bin/env python3
"""AI Agent V1 — 7 场景统一入口。

场景清单（与 [`../../docs/ai-agent-v1-plan.md`](../../docs/ai-agent-v1-plan.md) Phase 2 对齐）：

| # | 场景 | 风险等级 | 工具链 |
|---|------|----------|--------|
| 1 | 本周销售情况 | low | shipment_records.query |
| 2 | 创建订单 | medium | customers.ensure_exists → shipment_generate.generate |
| 3 | 标记发货 | medium | shipment_records.update（mock 工具）|
| 4 | 库存补货 | medium | inventory.query → purchase.draft（mock）|
| 5 | OCR 失败重跑 | low | ocr.retry（mock 工具）|
| 6 | 发货通知 | medium | wechat_send.preview |
| 7 | 导 Excel | low | excel_export.run（mock 工具）|

证据写入 ``docs/evidence/ai-agent-v1/scenario-N-<stamp>.json``。

示例（在 FHD 根目录）::

    python3 scripts/ai_agent_v1/run_demo_v1.py --scenario all
    python3 scripts/ai_agent_v1/run_demo_v1.py --scenario 2 --strategy auto
    python3 scripts/ai_agent_v1/run_demo_v1.py --scenario 6 --strategy interactive
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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
    """V0/V1 同款 stub，避免 demo CLI 强依赖 PG 向量库。"""
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


def _mock_dispatcher(
    tool_id: str, action: str, params: dict[str, Any]
) -> dict[str, Any]:
    """
    无 DB 时的工具桩：仍经 WorkflowEngine 调度。
    注意：仅 mock 已实现工具的关键调用；未知工具返回 NOT_IMPLEMENTED。
    """
    key = (tool_id, action)

    if key == ("shipment_records", "query"):
        return {
            "success": True,
            "data": [
                {"order_number": "MOCK-001", "unit_name": "上海宏达", "amount": 12500.0},
                {"order_number": "MOCK-002", "unit_name": "七彩乐园", "amount": 9800.0},
            ],
            "message": "mock: 2 条本周销售记录",
        }
    if key == ("customers", "ensure_exists"):
        return {
            "success": True,
            "id": 1001,
            "customer_name": params.get("unit_name", "mock-customer"),
            "unit_name": params.get("unit_name", "mock-customer"),
            "created": False,
        }
    if key == ("shipment_generate", "generate"):
        return {
            "success": True,
            "id": 5001,
            "order_number": f"MOCK-{datetime.now(timezone.utc).strftime('%Y%m%d')}-001",
            "message": "mock: 发货单已生成",
        }
    if key == ("inventory", "query"):
        return {
            "success": True,
            "data": [
                {"model_number": "9702-C", "stock": 200, "reorder_threshold": 500},
            ],
            "message": "mock: 1 条低于阈值的库存",
        }
    if key == ("wechat_send", "preview"):
        return {
            "success": True,
            "data": [
                {"contact_id": 1, "name": "上海宏达-王经理", "wechat_id": "wx-mock-1"},
            ],
            "message": "mock: 1 个匹配联系人",
        }
    if key == ("excel_export", "run"):
        return {
            "success": True,
            "file_path": "/tmp/mock-shipment-week.xlsx",
            "rows": 25,
            "message": "mock: 已导出 25 行",
        }
    if key == ("ocr", "retry"):
        return {
            "success": True,
            "reprocessed": 3,
            "message": "mock: 已重跑 3 张发票",
        }
    if key == ("shipment_records", "update"):
        return {
            "success": True,
            "updated": 1,
            "message": "mock: 发货状态已更新",
        }
    if key == ("purchase", "draft"):
        return {
            "success": True,
            "purchase_order_id": "MOCK-PO-001",
            "message": "mock: 采购单草稿已创建",
        }
    return {"success": False, "message": f"mock 未实现: {tool_id}.{action}"}


@dataclass
class Scenario:
    scenario_id: int
    title: str
    user_message: str
    plan_builder: Callable[[str], Any]
    risk: str  # low | medium | high


def _build_plan_sales_query(plan_id: str) -> Any:
    from app.application.workflow.types import PlanGraph, WorkflowNode

    return PlanGraph(
        plan_id=plan_id,
        intent="weekly_sales_summary",
        todo_steps=["查询本周出货记录", "聚合并输出"],
        nodes=[
            WorkflowNode(
                node_id="query_shipments",
                tool_id="shipment_records",
                action="query",
                params={"limit": 50, "date_from": "2026-06-01", "date_to": "2026-06-07"},
                risk="low",
                idempotent=True,
                description="查询本周出货记录",
            )
        ],
        risk_level="low",
    )


def _build_plan_create_order(plan_id: str) -> Any:
    from app.application.workflow.types import PlanGraph, WorkflowNode

    return PlanGraph(
        plan_id=plan_id,
        intent="create_order_for_unit",
        todo_steps=["确保客户存在", "生成发货单"],
        nodes=[
            WorkflowNode(
                node_id="ensure_customer",
                tool_id="customers",
                action="ensure_exists",
                params={"unit_name": "上海宏达公司"},
                risk="medium",
                idempotent=True,
            ),
            WorkflowNode(
                node_id="generate_shipment",
                tool_id="shipment_generate",
                action="generate",
                params={
                    "unit_name": "上海宏达公司",
                    "products": [{"model_number": "9702-C", "quantity": 1000, "unit_price": 12.5}],
                },
                risk="medium",
                depends_on=["ensure_customer"],
            ),
        ],
        risk_level="medium",
    )


def _build_plan_mark_shipped(plan_id: str) -> Any:
    from app.application.workflow.types import PlanGraph, WorkflowNode

    return PlanGraph(
        plan_id=plan_id,
        intent="mark_shipment_shipped",
        todo_steps=["查询订单", "更新发货状态"],
        nodes=[
            WorkflowNode(
                node_id="query_order",
                tool_id="shipment_records",
                action="query",
                params={"order_number": "MOCK-20260605-001"},
                risk="low",
                idempotent=True,
            ),
            WorkflowNode(
                node_id="update_status",
                tool_id="shipment_records",
                action="update",
                params={"order_number": "MOCK-20260605-001", "status": "shipped"},
                risk="medium",
                depends_on=["query_order"],
            ),
        ],
        risk_level="medium",
    )


def _build_plan_inventory_reorder(plan_id: str) -> Any:
    from app.application.workflow.types import PlanGraph, WorkflowNode

    return PlanGraph(
        plan_id=plan_id,
        intent="reorder_low_stock",
        todo_steps=["查询低库存", "起草采购单"],
        nodes=[
            WorkflowNode(
                node_id="query_inventory",
                tool_id="inventory",
                action="query",
                params={"below_threshold": True},
                risk="low",
                idempotent=True,
            ),
            WorkflowNode(
                node_id="draft_po",
                tool_id="purchase",
                action="draft",
                params={"model_number": "9702-C", "quantity": 500, "supplier": "默认供应商"},
                risk="medium",
                depends_on=["query_inventory"],
            ),
        ],
        risk_level="medium",
    )


def _build_plan_ocr_retry(plan_id: str) -> Any:
    from app.application.workflow.types import PlanGraph, WorkflowNode

    return PlanGraph(
        plan_id=plan_id,
        intent="ocr_retry_failed",
        todo_steps=["重跑失败发票"],
        nodes=[
            WorkflowNode(
                node_id="ocr_retry",
                tool_id="ocr",
                action="retry",
                params={"failed_only": True, "limit": 3},
                risk="low",
                idempotent=True,
            )
        ],
        risk_level="low",
    )


def _build_plan_wechat_notify(plan_id: str) -> Any:
    from app.application.workflow.types import PlanGraph, WorkflowNode

    return PlanGraph(
        plan_id=plan_id,
        intent="notify_customer_shipped",
        todo_steps=["查询匹配联系人", "生成发送预览"],
        nodes=[
            WorkflowNode(
                node_id="lookup_contact",
                tool_id="wechat_send",
                action="preview",
                params={"keyword": "上海宏达"},
                risk="low",
                idempotent=True,
            )
        ],
        risk_level="low",
    )


def _build_plan_excel_export(plan_id: str) -> Any:
    from app.application.workflow.types import PlanGraph, WorkflowNode

    return PlanGraph(
        plan_id=plan_id,
        intent="export_shipment_excel",
        todo_steps=["导出本周发货数据"],
        nodes=[
            WorkflowNode(
                node_id="export_excel",
                tool_id="excel_export",
                action="run",
                params={"date_from": "2026-06-01", "date_to": "2026-06-07"},
                risk="low",
                idempotent=True,
            )
        ],
        risk_level="low",
    )


SCENARIOS: list[Scenario] = [
    Scenario(
        scenario_id=1,
        title="本周销售情况",
        user_message="看看本周销售情况怎么样",
        plan_builder=_build_plan_sales_query,
        risk="low",
    ),
    Scenario(
        scenario_id=2,
        title="创建订单",
        user_message="给客户上海宏达公司创建一张订单：1000 个 9702-C 型号，单价 12.5",
        plan_builder=_build_plan_create_order,
        risk="medium",
    ),
    Scenario(
        scenario_id=3,
        title="标记发货",
        user_message="把订单 MOCK-20260605-001 标记为已发货",
        plan_builder=_build_plan_mark_shipped,
        risk="medium",
    ),
    Scenario(
        scenario_id=4,
        title="库存补货",
        user_message="查一下库存，低于阈值的起草采购单",
        plan_builder=_build_plan_inventory_reorder,
        risk="medium",
    ),
    Scenario(
        scenario_id=5,
        title="OCR 失败重跑",
        user_message="把昨天 OCR 识别失败的 3 张发票重跑一下",
        plan_builder=_build_plan_ocr_retry,
        risk="low",
    ),
    Scenario(
        scenario_id=6,
        title="发货通知",
        user_message="给上海宏达发送发货通知",
        plan_builder=_build_plan_wechat_notify,
        risk="low",
    ),
    Scenario(
        scenario_id=7,
        title="导出 Excel",
        user_message="把本周的发货数据导成 Excel",
        plan_builder=_build_plan_excel_export,
        risk="low",
    ),
]


def _default_output_path(scenario_id: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return EVIDENCE_DIR / f"scenario-{scenario_id}-{stamp}.json"


def run_scenario(
    scenario: Scenario,
    strategy: str,
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
        dispatcher = _mock_dispatcher
        execution_mode = "mock"
    elif force_live or _database_reachable():
        dispatcher = _dispatch_workflow_tool
        execution_mode = "live"
    else:
        dispatcher = _mock_dispatcher
        execution_mode = "mock"

    engine = WorkflowEngine(tool_dispatcher=dispatcher)
    gated = ApprovalGatedEngine(engine=engine)

    plan_id = f"v1-s{scenario.scenario_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    plan = scenario.plan_builder(plan_id)
    runtime_ctx: dict[str, Any] = {
        "user_id": f"v1_scenario_{scenario.scenario_id}",
        "message": scenario.user_message,
        "scenario_id": scenario.scenario_id,
    }

    decision, run_result = gated.run(plan=plan, runtime_context=runtime_ctx, strategy=strategy)

    evidence = build_gated_evidence(
        input_message=scenario.user_message,
        plan=plan,
        decision=decision,
        run_result=run_result,
        execution_mode=execution_mode,
        strategy=strategy,
    )
    evidence["scenario_id"] = scenario.scenario_id
    evidence["scenario_title"] = scenario.title

    out = output_path or _default_output_path(scenario.scenario_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence["_evidence_path"] = str(out)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Agent V1 7 场景统一入口")
    parser.add_argument(
        "--scenario",
        type=str,
        default="all",
        help="场景号 1-7，或 'all'。映射见 SCENARIOS。",
    )
    parser.add_argument(
        "--strategy",
        choices=["auto", "interactive", "reject"],
        default="auto",
        help="审批策略（仅 medium 风险节点受影响）",
    )
    args = parser.parse_args(argv)

    _bootstrap()

    if args.scenario == "all":
        targets = SCENARIOS
    else:
        try:
            sid = int(args.scenario)
        except ValueError:
            print(f"无效场景号: {args.scenario}", file=sys.stderr)
            return 2
        targets = [s for s in SCENARIOS if s.scenario_id == sid]
        if not targets:
            print(f"场景 {sid} 不存在", file=sys.stderr)
            return 2

    print(f"=== AI Agent V1 — 共 {len(targets)} 场景 / strategy={args.strategy} ===")
    failures = 0
    for sc in targets:
        print(f"\n[{sc.scenario_id}] {sc.title}: {sc.user_message}")
        try:
            ev = run_scenario(sc, strategy=args.strategy)
            decision = ev.get("gated_decision") or {}
            print(
                f"  success={ev.get('success')} plan_id={ev.get('plan_id')} "
                f"approved={decision.get('all_approved')} "
                f"pending={decision.get('pending_approval')} "
                f"rejected={decision.get('any_rejected')}"
            )
            print(f"  evidence: {ev.get('_evidence_path')}")
        except Exception as e:
            failures += 1
            print(f"  ERROR: {e}")
            traceback.print_exc()

    if failures:
        print(f"\n=== {failures} 场景失败 ===")
        return 1
    print(f"\n=== 全部 {len(targets)} 场景完成 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
