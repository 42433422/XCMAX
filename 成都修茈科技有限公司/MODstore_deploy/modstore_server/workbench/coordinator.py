"""Coordinator for workbench delivery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Dict, List, cast

from sqlalchemy.orm import Session

from modstore_server.models import User
from modstore_server.workbench.intent import CANVAS_SKILL_INTENT, _canonical_workbench_intent
from modstore_server.workbench.sessions import ProgressCallbacks, SessionStore

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class PipelinePorts:
    sessions: SessionStore
    progress: ProgressCallbacks
    database: Callable[[], Callable[[], Session]]
    resolve_model: Callable[..., Awaitable[tuple[str | None, str | None]]]
    craft_step: Callable[..., Awaitable[dict[str, Any] | None]]
    script: Callable[..., Awaitable[None]]
    suite: Callable[..., Awaitable[None]]
    employee: Callable[..., Awaitable[None]]
    canvas: Callable[..., Awaitable[None]]


async def _run_pipeline(
    sid: str, user_id: int, payload: Dict[str, Any], *, ports: PipelinePorts
) -> None:
    intent = _canonical_workbench_intent(str(payload.get("intent") or ""))
    payload["intent"] = intent
    execution_mode = str(payload.get("execution_mode") or "workflow")
    brief = (payload.get("brief") or "").strip()
    prov = (payload.get("provider") or "").strip() or None
    mdl = (payload.get("model") or "").strip() or None
    replace = bool(payload.get("replace", True))
    gen_wf_graph = bool(payload.get("generate_workflow_graph", True))
    generate_frontend = bool(payload.get("generate_frontend", True))
    sf = ports.database()
    with sf() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await ports.progress.fail(sid, "spec", "用户不存在")
            return
        if not prov or not mdl:
            _auto_prov, _auto_mdl = await ports.resolve_model(db, user_id)
            if not prov:
                prov = _auto_prov
            if not mdl:
                mdl = _auto_mdl
        from modstore_server.employee_brief_utils import extract_routing_brief

        _routing_brief = extract_routing_brief(payload, fallback=brief)
        await ports.progress.set_step(sid, "spec", "running")
        _spec_result = await ports.craft_step(
            "spec",
            db=db,
            user_id=cast(int, user.id),
            payload=payload,
            brief=brief,
            routing_brief=_routing_brief,
            prov=prov,
            mdl=mdl,
        )
        spec_warnings: List[str] = []
        _brief_domain_hints: List[str] = []
        _structured_requirement: Dict[str, Any] = {}
        if _spec_result is not None:
            spec_warnings = _spec_result.get("spec_warnings", [])
            _brief_domain_hints = _spec_result.get("brief_domain_hints", [])
            _structured_requirement = _spec_result.get("structured_requirement") or {}
            if _spec_result.get("routing_brief"):
                _routing_brief = (
                    str(_spec_result.get("routing_brief") or _routing_brief).strip()
                    or _routing_brief
                )
        spec_msg = "用户校验通过"
        if spec_warnings:
            spec_msg += "；" + "；".join(spec_warnings[:3])
        if _brief_domain_hints:
            spec_msg += f"；识别领域：{'、'.join(_brief_domain_hints[:4])}"
        async with ports.sessions.lock:
            sess = ports.sessions.data.get(sid)
            if sess:
                sess["spec_warnings"] = spec_warnings
                sess["spec_domain_hints"] = _brief_domain_hints
                sess["structured_requirement"] = _structured_requirement
                sess["routing_brief"] = _routing_brief
                ports.sessions.persist(sid)
        await ports.progress.set_step(sid, "spec", "done", spec_msg[:480])
        if execution_mode == "script":
            await ports.script(sid, user_id, payload, execution_mode, brief, prov, mdl, db)
            return
        if intent == "mod":
            await ports.suite(
                sid, payload, intent, brief, prov, mdl, replace, generate_frontend, db, user
            )
            return
        if intent == "employee":
            await ports.employee(sid, user_id, payload, intent, brief, prov, mdl, replace, db, user)
            return
        if intent == CANVAS_SKILL_INTENT:
            await ports.canvas(sid, payload, intent, brief, prov, mdl, gen_wf_graph, db, user)
            return
        await ports.progress.fail(sid, "spec", f"未知 intent: {intent}")
