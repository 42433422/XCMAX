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
from fastapi.responses import JSONResponse

from app.fastapi_routes.tools_execute import run_tools_execute_agent
from app.schemas.finance_schema import FinanceTransactionCreate, FinanceTransactionUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/finance", tags=["finance"])


def _svc():
    from app.application.finance_app_service import FinanceAppService

    return FinanceAppService()


def _parse_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _run_finance_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> JSONResponse:
    result, status = run_tools_execute_agent(
        request=request,
        body={"tool_id": "finance", "action": action, "params": params},
        route_path=route_path,
    )
    return JSONResponse(result, status_code=status)


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
