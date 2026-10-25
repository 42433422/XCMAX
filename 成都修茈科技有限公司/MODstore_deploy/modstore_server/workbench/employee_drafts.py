"""Employee drafts for workbench delivery."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict, cast

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.models import User
from modstore_server.workbench.schemas import (
    EmployeeAiDraftBody,
    EmployeeAiRefinePromptBody,
)

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class DraftPorts:
    database: Callable[[], Callable[[], Session]]
    resolve_model: Callable[..., Awaitable[tuple[str | None, str | None, str | None]]]
    generate_workflow: Callable[..., Awaitable[dict[str, Any]]]


async def employee_ai_draft(
    body: EmployeeAiDraftBody,
    user: User = Depends(_get_current_user),
    *,
    ports: DraftPorts,
):
    """SSE 事件序列：stage_start / stage_progress / stage_done / stage_error / pipeline_done。

    ``pipeline_done`` 携带完整 manifest；客户端可在收到后离线编辑，再调 ``/api/mods/ai-scaffold``
    或 ``import_zip`` 落库上架（保持与现有 employee 工作台链路兼容）。
    """
    from modstore_server.employee_ai_pipeline import run_pipeline
    from modstore_server.llm_key_resolver import (
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        resolve_api_key,
        resolve_base_url,
    )
    from modstore_server.script_agent.llm_client import RealLlmClient

    sf = ports.database()

    async def _stream() -> AsyncIterator[bytes]:
        with sf() as db:
            prov, mdl, err = await ports.resolve_model(db, user, body.provider, body.model)
            if err or not prov or not mdl:
                err_ev = {"event": "pipeline_error", "stage": "init", "error": err}
                yield f"data: {json.dumps(err_ev, ensure_ascii=False)}\n\n".encode()
                return
            api_key, _ = resolve_api_key(db, cast(int, user.id), prov)
            if not api_key:
                err_ev = {
                    "event": "pipeline_error",
                    "stage": "init",
                    "error": "该供应商未配置可用 API Key",
                }
                yield f"data: {json.dumps(err_ev, ensure_ascii=False)}\n\n".encode()
                return
            base_url = (
                resolve_base_url(db, cast(int, user.id), prov)
                if prov in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
                else None
            )
            llm = RealLlmClient(
                prov,
                api_key=api_key,
                model=mdl,
                base_url=base_url,
                forbid_reasoning_fallback=True,
            )
            from modstore_server.models import Workflow as WorkflowModel

            wf_rows = (
                db.query(WorkflowModel)
                .filter(
                    WorkflowModel.user_id == cast(int, user.id),
                    WorkflowModel.is_active.is_(True),
                )
                .order_by(WorkflowModel.updated_at.desc())
                .limit(20)
                .all()
            )
            eligible_wfs = [
                {
                    "id": w.id,
                    "name": w.name or "",
                    "description": w.description or "",
                    "sandbox_passed": bool(getattr(w, "sandbox_passed_for_current_graph", False)),
                }
                for w in wf_rows
            ]

            async def _gen_wf_fallback() -> Dict[str, Any]:
                _pack_id = (body.suggested_id or "").strip() or None
                _pack_label = (body.brief[:40] if body.brief else "").strip() or _pack_id
                with sf() as db2:
                    return await ports.generate_workflow(
                        db2,
                        user,
                        role=body.brief[:40],
                        scenario=body.brief[:120],
                        workflow_name=f"AI 员工工作流 - {(body.suggested_id or body.brief[:16]).strip()}",
                        provider=prov,
                        model=mdl,
                        target_employee_pack_id=_pack_id,
                        target_employee_label=_pack_label,
                    )

            q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

            async def _on_ev(ev: Dict[str, Any]) -> None:
                await q.put(ev)

            async def _run_and_sentinel() -> None:
                try:
                    await run_pipeline(
                        body.brief,
                        llm=llm,
                        on_event=_on_ev,
                        eligible_workflows=eligible_wfs,
                        generate_workflow_fallback=_gen_wf_fallback,
                    )
                finally:
                    await q.put(None)

            task = asyncio.create_task(_run_and_sentinel())
            try:
                while True:
                    ev = await q.get()
                    if ev is None:
                        break
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()
                await task
            finally:
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def employee_ai_refine_prompt(
    body: EmployeeAiRefinePromptBody,
    user: User = Depends(_get_current_user),
    *,
    ports: DraftPorts,
):
    """用 LLM 重写 employee system prompt，返回优化后文本与一句话 diff 说明。"""
    from modstore_server.employee_ai_pipeline import refine_system_prompt
    from modstore_server.llm_key_resolver import (
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        resolve_api_key,
        resolve_base_url,
    )
    from modstore_server.script_agent.llm_client import RealLlmClient

    sf = ports.database()
    with sf() as db:
        prov, mdl, err = await ports.resolve_model(db, user, body.provider, body.model)
        if err or not prov or not mdl:
            raise HTTPException(400, err or "未解析出可用模型")
        api_key, _ = resolve_api_key(db, cast(int, user.id), prov)
        if not api_key:
            raise HTTPException(400, "该供应商未配置可用 API Key")
        base_url = (
            resolve_base_url(db, cast(int, user.id), prov)
            if prov in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
            else None
        )
    llm = RealLlmClient(
        prov,
        api_key=api_key,
        model=mdl,
        base_url=base_url,
        forbid_reasoning_fallback=True,
    )
    result, err = await refine_system_prompt(
        current_prompt=body.current_prompt,
        instruction=body.instruction,
        role_context=body.role_context,
        llm=llm,
    )
    if err or result is None:
        raise HTTPException(502, f"Prompt 优化失败: {err or '未知错误'}")
    return result
