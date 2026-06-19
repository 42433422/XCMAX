"""
财务管理 API 路由

提供财务看板、应收/应付账款查询、手工凭证 CRUD 及月度趋势分析。
数据来源：
  - 实时派生：ShipmentRecord（收入）、PurchaseOrder（成本/应付）
  - 手工凭证：FinancialTransaction 表

端点前缀：/api/finance
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request

from app.schemas.finance_schema import FinanceTransactionCreate, FinanceTransactionUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/finance", tags=["finance"])


def _svc():
    from app.application.finance_app_service import FinanceAppService

    return FinanceAppService()


def _parse_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _agent_node_output(run: Any, node_id: str) -> dict[str, Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                break
    if not output:
        output = {"success": getattr(run, "status", "") == "completed"}
    if not output.get("success") and getattr(run, "error", "") and not output.get("message"):
        output["message"] = getattr(run, "error", "")
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return output


def _finance_agent_user_id(request: Request, payload: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or payload.get("user_id")
        or payload.get("userId")
        or "finance-route"
    ).strip()


def _run_finance_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.services.tools_execution.registry import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("finance") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {
            "success": False,
            "message": f"未注册的 finance 动作: {action}",
            "agent_status": "failed",
        }

    node_id = f"finance_{action}"
    user_id = _finance_agent_user_id(request, params)
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 finance.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="finance",
                action=action,
                params=dict(params or {}),
                risk=str(action_meta.get("risk") or "high"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute finance.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "high"),
        metadata={"source": "finance_route", "route": route_path},
    )
    runtime_context = {
        "source": "finance_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
        "service_source": "fastapi_finance_route",
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(params.get("message") or f"Finance {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status == "waiting_user":
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "finance-route",
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return _agent_node_output(run, node_id)


# ── 财务看板 ─────────────────────────────────────────────────────


@router.get("/dashboard")
def finance_dashboard(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
):
    """财务总览：收入、成本、毛利、应付款汇总。"""
    return _svc().get_dashboard(
        start_date=_parse_dt(start_date),
        end_date=_parse_dt(end_date),
    )


@router.get("/trend")
def finance_monthly_trend(year: int | None = Query(default=None)):
    """按月统计收入/成本/利润趋势。"""
    return _svc().get_monthly_trend(year=year)


# ── 应收账款 ─────────────────────────────────────────────────────


@router.get("/receivables")
def finance_receivables(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=20),
):
    """应收账款列表（手工凭证）。"""
    return _svc().get_receivables(
        start_date=_parse_dt(start_date),
        end_date=_parse_dt(end_date),
        status=status,
        page=page,
        per_page=per_page,
    )


# ── 应付账款 ─────────────────────────────────────────────────────


@router.get("/payables")
def finance_payables(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=20),
):
    """应付账款列表（派生自采购订单未付余额）。"""
    return _svc().get_payables(
        start_date=_parse_dt(start_date),
        end_date=_parse_dt(end_date),
        status=status,
        page=page,
        per_page=per_page,
    )


# ── 财务凭证 CRUD ─────────────────────────────────────────────────


@router.get("/transactions")
def finance_transactions(
    transaction_type: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=20),
):
    """财务凭证列表。transaction_type: revenue|expense|receivable|payable|receipt|payment|adjustment"""
    return _svc().list_transactions(
        transaction_type=transaction_type,
        start_date=_parse_dt(start_date),
        end_date=_parse_dt(end_date),
        status=status,
        page=page,
        per_page=per_page,
    )


@router.get("/transactions/{txn_id}")
def finance_transaction_get(txn_id: int):
    return _svc().get_transaction(txn_id)


@router.post("/transactions")
def finance_transaction_create(request: Request, body: FinanceTransactionCreate):
    """新建财务凭证。必填：transaction_type, amount。"""
    return _run_finance_agent(
        request=request,
        action="create_transaction",
        params=body.model_dump(exclude_none=True),
        route_path="/api/finance/transactions",
    )


@router.put("/transactions/{txn_id}")
def finance_transaction_update(request: Request, txn_id: int, body: FinanceTransactionUpdate):
    return _run_finance_agent(
        request=request,
        action="update_transaction",
        params={"transaction_id": txn_id, **body.model_dump(exclude_none=True)},
        route_path="/api/finance/transactions/{txn_id}",
    )


@router.delete("/transactions/{txn_id}")
def finance_transaction_delete(request: Request, txn_id: int):
    return _run_finance_agent(
        request=request,
        action="delete_transaction",
        params={"transaction_id": txn_id},
        route_path="/api/finance/transactions/{txn_id}",
    )


# unified-ledger 见 finance_unified_ledger.py（独立注册，避免本模块 schema 导入失败时端点不可用）
