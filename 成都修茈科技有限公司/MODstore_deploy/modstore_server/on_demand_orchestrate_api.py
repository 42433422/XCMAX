"""按需编排 API：立即触发编排任务，支持自然语言描述 + 多员工并行执行。

POST /api/ops/orchestrate          — 立即编排（同步，会阻塞直到完成）
POST /api/ops/orchestrate/async    — 异步编排（立即返回 job_id，轮询状态）
GET  /api/ops/orchestrate/jobs/{job_id}      — 查询单条异步任务状态
GET  /api/ops/orchestrate/jobs               — 查询当前用户最近的异步任务列表

2026-05 起：异步任务状态写入数据库 ``OnDemandOrchestrateJob``，跨进程可见、
进程重启不丢失（替代了原先单进程内存字典）。
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modstore_server.api.deps import _get_current_user
from modstore_server.models import OnDemandOrchestrateJob, User, get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ops", tags=["ops"])


def _safe_loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _extract_dispatch_source(row: OnDemandOrchestrateJob) -> str:
    raw = (row.result_json or "").strip()
    if not raw:
        return "web"
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            meta = parsed.get("_meta")
            if isinstance(meta, dict) and meta.get("dispatch_source"):
                return str(meta.get("dispatch_source"))
    except Exception:
        pass
    return "web"


def _job_to_dict(row: OnDemandOrchestrateJob) -> Dict[str, Any]:
    result_payload = _safe_loads(row.result_json) if (row.result_json or "").strip() else None
    if isinstance(result_payload, dict) and "_meta" in result_payload:
        result_payload = {k: v for k, v in result_payload.items() if k != "_meta"}
        if "payload" in result_payload and len(result_payload) == 1:
            result_payload = result_payload.get("payload")
    return {
        "job_id": row.job_id,
        "status": row.status,
        "task_description": (row.task_description or "")[:200],
        "dispatch_source": _extract_dispatch_source(row),
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "result": result_payload,
        "error": (row.error or "") or None,
    }


class OrchestrateRequest(BaseModel):
    task_description: str = Field(
        ..., min_length=1, max_length=2000, description="自然语言任务描述"
    )
    use_task_router: bool = Field(
        True, description="是否用 LLM 拆解子任务（False 时走单 daily-orchestrator）"
    )
    target_employee_id: Optional[str] = Field(
        None, description="use_task_router=False 时指定单员工"
    )
    max_concurrency: int = Field(2, ge=1, le=8)
    allow_high_risk_real_run: bool = Field(False)
    llm_provider: str = Field("auto")
    llm_model: str = Field("auto")
    dispatch_source: Optional[str] = Field("web", description="任务来源：desktop | web")


@router.post("/orchestrate", summary="立即触发编排任务（同步）")
async def orchestrate_now(
    body: OrchestrateRequest,
    user: User = Depends(_get_current_user),
):
    """接收自然语言任务描述，立即通过 task_router 拆解并执行。"""
    import asyncio

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: _run_orchestrate(body, int(user.id)))
    return result


@router.post("/orchestrate/async", summary="异步触发编排任务（返回 job_id）")
async def orchestrate_async(
    body: OrchestrateRequest,
    user: User = Depends(_get_current_user),
):
    """提交编排任务，立即返回 job_id，可轮询 ``/api/ops/orchestrate/jobs/{job_id}``。"""
    job_id = str(uuid.uuid4())
    sf = get_session_factory()
    with sf() as session:
        row = OnDemandOrchestrateJob(
            job_id=job_id,
            user_id=int(user.id),
            task_description=(body.task_description or "")[:8000],
            status="pending",
            use_task_router=bool(body.use_task_router),
            target_employee_id=(body.target_employee_id or "")[:128],
            max_concurrency=int(body.max_concurrency),
            allow_high_risk_real_run=bool(body.allow_high_risk_real_run),
            llm_provider=str(body.llm_provider or "auto")[:64],
            llm_model=str(body.llm_model or "auto")[:128],
            result_json=json.dumps(
                {"_meta": {"dispatch_source": (body.dispatch_source or "web").strip() or "web"}},
                ensure_ascii=False,
            ),
        )
        session.add(row)
        session.commit()

    body_copy = body.model_copy()
    user_id = int(user.id)

    def _worker():
        sf2 = get_session_factory()
        with sf2() as session:
            r = session.query(OnDemandOrchestrateJob).filter_by(job_id=job_id).first()
            if r:
                r.status = "running"
                r.started_at = datetime.now(timezone.utc)
                session.commit()
        try:
            result = _run_orchestrate(body_copy, user_id)
            with sf2() as session:
                r = session.query(OnDemandOrchestrateJob).filter_by(job_id=job_id).first()
                if r:
                    r.status = "done"
                    r.completed_at = datetime.now(timezone.utc)
                    meta = _extract_dispatch_source(r)
                    wrapped = {"_meta": {"dispatch_source": meta}, "payload": result}
                    r.result_json = json.dumps(wrapped, ensure_ascii=False)[:500_000]
                    session.commit()
        except Exception as exc:
            logger.exception("async orchestrate job %s failed", job_id)
            with sf2() as session:
                r = session.query(OnDemandOrchestrateJob).filter_by(job_id=job_id).first()
                if r:
                    r.status = "failed"
                    r.completed_at = datetime.now(timezone.utc)
                    r.error = str(exc)[:4000]
                    session.commit()

    t = threading.Thread(target=_worker, daemon=True, name=f"orchestrate-{job_id[:8]}")
    t.start()

    return {"ok": True, "job_id": job_id, "status": "pending"}


@router.get("/orchestrate/jobs/{job_id}", summary="查询异步编排任务状态")
async def get_orchestrate_job(
    job_id: str,
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        row = session.query(OnDemandOrchestrateJob).filter_by(job_id=job_id).first()
        if not row:
            raise HTTPException(404, f"job_id {job_id} not found")
        # 仅本人或管理员可见
        if int(row.user_id) != int(user.id) and not bool(getattr(user, "is_admin", False)):
            raise HTTPException(403, "forbidden")
        return _job_to_dict(row)


@router.get("/orchestrate/jobs", summary="查询当前用户最近的异步编排任务列表")
async def list_orchestrate_jobs(
    user: User = Depends(_get_current_user),
    limit: int = 20,
):
    limit = max(1, min(int(limit), 100))
    sf = get_session_factory()
    with sf() as session:
        q = session.query(OnDemandOrchestrateJob)
        if not bool(getattr(user, "is_admin", False)):
            q = q.filter(OnDemandOrchestrateJob.user_id == int(user.id))
        rows = q.order_by(OnDemandOrchestrateJob.id.desc()).limit(limit).all()
        return {"ok": True, "items": [_job_to_dict(r) for r in rows]}


def _run_orchestrate(body: OrchestrateRequest, user_id: int) -> Dict[str, Any]:
    if body.use_task_router:
        from modstore_server.task_router import route_and_dispatch

        return route_and_dispatch(
            body.task_description,
            created_by_user_id=user_id,
            llm_provider=body.llm_provider,
            llm_model=body.llm_model,
            max_concurrency=body.max_concurrency,
            allow_high_risk_real_run=body.allow_high_risk_real_run,
        )
    else:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        target = (body.target_employee_id or "daily-orchestrator").strip()
        return plan_and_dispatch(
            body.task_description,
            {},
            target_employee_id=target,
            created_by_user_id=user_id,
            max_concurrency=body.max_concurrency,
            allow_high_risk_real_run=body.allow_high_risk_real_run,
        )
