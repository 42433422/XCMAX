"""管理员：在岗员工图执行能力与图级编排运行 API。"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.api.deps import require_admin
from modstore_server.employee_executor import list_employees as list_employees_exec
from modstore_server.employee_runtime import load_employee_pack, parse_employee_config_v2
from modstore_server.integrations.ops_action_handlers import OPS_COMMAND_REGISTRY
from modstore_server.llm_crypto import fernet_configured
from modstore_server.llm_key_resolver import KNOWN_PROVIDERS, credential_status
from modstore_server.models import (
    DutyGraphRun,
    DutyGraphRunNode,
    EmployeeExecutionMetric,
    OpsActionAuditLog,
    User,
    get_session_factory,
)
from modstore_server.services.employee import get_default_employee_client

router = APIRouter(prefix="/api/admin", tags=["admin-duty-graph"])

_HIGH_RISK_HANDLERS = frozenset(
    {"shell_exec", "ssh_exec", "vibe_edit", "vibe_heal", "vibe_code", "openapi_tool", "agent"}
)
_LLM_FREE_HANDLERS = frozenset({"echo", "webhook"})
_MAX_RUN_INPUT_BYTES = 100_000
_MAX_RESULT_BYTES = 60_000


def _json_dumps(obj: Any, *, max_chars: int = 0) -> str:
    text = json.dumps(obj, ensure_ascii=False)
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "…"
    return text


def _json_loads(text: str, default: Any) -> Any:
    raw = (text or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _as_str(v: Any) -> str:
    return str(v or "").strip()


def _extract_manifest_dependencies(manifest: Mapping[str, Any]) -> List[str]:
    """Collaboration-only deps for duty-graph execution order.

    Reads only ``depends_on`` and ``employee_config_v2.collaboration.depends_on``.
    Ignores ``release_hints`` / ``references`` (infra pointers); deploy topology lives in
    ``MODstore_deploy/orchestration/*.yaml``, not in manifest edges.
    """
    deps: List[str] = []
    root = manifest if isinstance(manifest, Mapping) else {}
    root_dep = root.get("depends_on")
    if isinstance(root_dep, list):
        deps.extend(_as_str(d) for d in root_dep)
    v2 = root.get("employee_config_v2")
    if isinstance(v2, Mapping):
        collab = v2.get("collaboration")
        if isinstance(collab, Mapping):
            raw = collab.get("depends_on")
            if isinstance(raw, list):
                deps.extend(_as_str(d) for d in raw)
    seen: Set[str] = set()
    out: List[str] = []
    for d in deps:
        if not d or d in seen:
            continue
        seen.add(d)
        out.append(d)
    return out


def _clean_handlers(actions_cfg: Mapping[str, Any]) -> List[str]:
    handlers_raw = actions_cfg.get("handlers")
    if not isinstance(handlers_raw, list):
        return ["echo"]
    out: List[str] = []
    for h in handlers_raw:
        hs = _as_str(h)
        if hs:
            out.append(hs)
    return out or ["echo"]


def _provider_has_usable_key(row: Mapping[str, Any] | None, fernet_ok: bool) -> bool:
    if not row:
        return False
    if bool(row.get("has_platform_key")):
        return True
    if bool(row.get("has_user_override")) and fernet_ok:
        return True
    return False


def _build_provider_status_map(session: Session, user_id: int) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for provider in KNOWN_PROVIDERS:
        out[provider] = credential_status(session, int(user_id), provider)
    return out


def _resolve_llm_state(
    *,
    handlers: Sequence[str],
    config: Mapping[str, Any],
    provider_status_map: Mapping[str, Mapping[str, Any]],
    fernet_ok: bool,
) -> Dict[str, Any]:
    needs_llm = any(_as_str(h) not in _LLM_FREE_HANDLERS for h in handlers)
    cog = config.get("cognition") if isinstance(config.get("cognition"), Mapping) else {}
    agent = (
        cog.get("agent")
        if isinstance(cog, Mapping) and isinstance(cog.get("agent"), Mapping)
        else {}
    )
    model_cfg = (
        agent.get("model")
        if isinstance(agent, Mapping) and isinstance(agent.get("model"), Mapping)
        else {}
    )
    provider = _as_str(model_cfg.get("provider")) or "auto"
    model_name = _as_str(model_cfg.get("model_name")) or "auto"
    is_auto = provider.lower() == "auto" or model_name.lower() == "auto"
    if is_auto:
        any_ok = any(
            _provider_has_usable_key(row, fernet_ok) for row in provider_status_map.values()
        )
        activated = (not needs_llm) or any_ok
        return {
            "provider": provider,
            "model": model_name,
            "needs_llm": needs_llm,
            "activated": activated,
            "key_source": "auto" if any_ok else "none",
        }
    row = provider_status_map.get(provider)
    has_platform = bool(row and row.get("has_platform_key"))
    has_byok = bool(row and row.get("has_user_override")) and fernet_ok
    credential_ok = has_platform or has_byok
    return {
        "provider": provider,
        "model": model_name,
        "needs_llm": needs_llm,
        "activated": (not needs_llm) or credential_ok,
        "key_source": "byok" if has_byok else ("platform" if has_platform else "none"),
    }


def _detect_risk(actions_cfg: Mapping[str, Any], handlers: Sequence[str]) -> Dict[str, Any]:
    details: List[Dict[str, Any]] = []
    for raw in handlers:
        handler = _as_str(raw)
        if not handler or handler not in _HIGH_RISK_HANDLERS:
            continue
        entry: Dict[str, Any] = {"handler": handler}
        if handler in ("shell_exec", "ssh_exec"):
            block = (
                actions_cfg.get(handler) if isinstance(actions_cfg.get(handler), Mapping) else {}
            )
            command_id = _as_str(block.get("command_id"))
            spec = OPS_COMMAND_REGISTRY.get(command_id)
            entry.update(
                {
                    "reason": "ops_command",
                    "command_id": command_id,
                    "requires_approval": bool(spec.requires_approval) if spec else False,
                }
            )
        elif handler.startswith("vibe_"):
            entry.update({"reason": "code_rewrite"})
        elif handler == "openapi_tool":
            entry.update({"reason": "external_api_side_effect"})
        elif handler == "agent":
            entry.update({"reason": "agentic_workspace_actions"})
        else:
            entry.update({"reason": "high_risk"})
        details.append(entry)
    return {
        "high_risk": bool(details),
        "requires_confirmation": bool(details),
        "details": details,
    }


def _latest_metric(session: Session, employee_id: str) -> Dict[str, Any] | None:
    row = (
        session.query(EmployeeExecutionMetric)
        .filter(EmployeeExecutionMetric.employee_id == employee_id)
        .order_by(EmployeeExecutionMetric.id.desc())
        .first()
    )
    if not row:
        return None
    return {
        "id": int(row.id),
        "status": _as_str(row.status),
        "task": _as_str(row.task),
        "duration_ms": float(row.duration_ms or 0.0),
        "llm_tokens": int(row.llm_tokens or 0),
        "error": _as_str(row.error),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _latest_ops_audits(session: Session, employee_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    rows = (
        session.query(OpsActionAuditLog)
        .filter(OpsActionAuditLog.employee_id == employee_id)
        .order_by(OpsActionAuditLog.id.desc())
        .limit(max(1, min(limit, 20)))
        .all()
    )
    return [
        {
            "id": int(r.id),
            "handler": _as_str(r.handler),
            "command_id": _as_str(r.command_id),
            "exit_code": r.exit_code,
            "dry_run": bool(r.dry_run),
            "approval_required": bool(r.approval_required),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def _load_manifest_for_employee(
    session: Session,
    employee_id: str,
    employee_index: Mapping[str, Mapping[str, Any]],
    manifest_cache: MutableMapping[str, Optional[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    if employee_id in manifest_cache:
        return manifest_cache[employee_id]
    row = employee_index.get(employee_id) or {}
    if _as_str(row.get("source")) == "v1_catalog":
        manifest_cache[employee_id] = None
        return None
    try:
        pack = load_employee_pack(session, employee_id)
        manifest = pack.get("manifest") if isinstance(pack, Mapping) else {}
        manifest_cache[employee_id] = manifest if isinstance(manifest, dict) else {}
    except Exception:
        manifest_cache[employee_id] = None
    return manifest_cache[employee_id]


def _analyze_employee_capability(
    session: Session,
    *,
    user_id: int,
    employee_row: Mapping[str, Any],
    provider_status_map: Mapping[str, Mapping[str, Any]],
    fernet_ok: bool,
    manifest_cache: MutableMapping[str, Optional[Dict[str, Any]]],
) -> Dict[str, Any]:
    employee_id = _as_str(employee_row.get("id"))
    source = _as_str(employee_row.get("source")) or "catalog"
    base: Dict[str, Any] = {
        "employee_id": employee_id,
        "name": _as_str(employee_row.get("name")) or employee_id,
        "source": source,
        "deployed": source != "v1_catalog",
        "executable": False,
        "reasons": [],
        "handlers": [],
        "declared_dependencies": [],
        "llm": {
            "provider": "auto",
            "model": "auto",
            "needs_llm": False,
            "activated": True,
            "key_source": "none",
        },
        "risk": {"high_risk": False, "requires_confirmation": False, "details": []},
        "recent_execution": _latest_metric(session, employee_id),
        "recent_ops_audits": _latest_ops_audits(session, employee_id, 5),
    }
    if source == "v1_catalog":
        base["reasons"] = ["仅目录登记（v1_catalog），未入库为可执行 employee_pack"]
        return base
    manifest = _load_manifest_for_employee(
        session, employee_id, {employee_id: employee_row}, manifest_cache
    )
    if not isinstance(manifest, dict):
        base["reasons"] = ["无法读取员工包 manifest"]
        return base

    cfg = parse_employee_config_v2(manifest)
    actions_cfg = cfg.get("actions") if isinstance(cfg.get("actions"), Mapping) else {}
    handlers = _clean_handlers(actions_cfg)
    deps = _extract_manifest_dependencies(manifest)
    llm_state = _resolve_llm_state(
        handlers=handlers,
        config=cfg,
        provider_status_map=provider_status_map,
        fernet_ok=fernet_ok,
    )
    risk_state = _detect_risk(actions_cfg, handlers)

    reasons: List[str] = []
    if llm_state.get("needs_llm") and not llm_state.get("activated"):
        reasons.append("缺少可用 LLM 密钥（平台密钥或可解密 BYOK）")

    base.update(
        {
            "handlers": handlers,
            "declared_dependencies": deps,
            "llm": llm_state,
            "risk": risk_state,
            "reasons": reasons,
            "executable": len(reasons) == 0,
        }
    )
    return base


def _topo_sort(
    nodes: Iterable[str], deps_map: Mapping[str, Sequence[str]]
) -> Tuple[List[str], List[str]]:
    node_set = set(nodes)
    indeg: Dict[str, int] = {n: 0 for n in node_set}
    children: Dict[str, List[str]] = {n: [] for n in node_set}
    for node in node_set:
        for dep in deps_map.get(node) or []:
            if dep not in node_set:
                continue
            indeg[node] += 1
            children[dep].append(node)

    queue: List[str] = sorted(n for n, deg in indeg.items() if deg == 0)
    out: List[str] = []
    while queue:
        cur = queue.pop(0)
        out.append(cur)
        for child in children.get(cur) or []:
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)
                queue.sort()
    if len(out) == len(node_set):
        return out, []
    cycle_nodes = sorted(n for n, deg in indeg.items() if deg > 0)
    return out, cycle_nodes


def _serialize_run(session: Session, run_id: int) -> Dict[str, Any]:
    run = session.get(DutyGraphRun, int(run_id))
    if not run:
        raise HTTPException(404, "运行记录不存在")
    rows = (
        session.query(DutyGraphRunNode)
        .filter(DutyGraphRunNode.run_id == run.id)
        .order_by(DutyGraphRunNode.order_index.asc(), DutyGraphRunNode.id.asc())
        .all()
    )
    items = []
    for r in rows:
        items.append(
            {
                "id": int(r.id),
                "employee_id": _as_str(r.employee_id),
                "order_index": int(r.order_index or 0),
                "depends_on": _json_loads(r.depends_on_json or "[]", []),
                "status": _as_str(r.status),
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_ms": float(r.duration_ms or 0.0),
                "llm_tokens": int(r.llm_tokens or 0),
                "metric_id": int(r.metric_id) if r.metric_id else None,
                "summary": _as_str(r.summary),
                "error": _as_str(r.error),
                "result": _json_loads(r.result_json or "{}", {}),
            }
        )
    return {
        "id": int(run.id),
        "created_by_user_id": int(run.created_by_user_id),
        "target_employee_id": _as_str(run.target_employee_id),
        "task": _as_str(run.task),
        "input_data": _json_loads(run.input_data_json or "{}", {}),
        "include_dependencies": bool(run.include_dependencies),
        "max_concurrency": int(run.max_concurrency or 1),
        "allow_high_risk_real_run": bool(run.allow_high_risk_real_run),
        "status": _as_str(run.status),
        "total_nodes": int(run.total_nodes or 0),
        "success_count": int(run.success_count or 0),
        "failed_count": int(run.failed_count or 0),
        "skipped_count": int(run.skipped_count or 0),
        "error": _as_str(run.error),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "nodes": items,
    }


@router.get("/employees/{employee_id}/execution-capability")
def get_employee_execution_capability(
    employee_id: str,
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _ = admin_user
    eid = _as_str(employee_id)
    if not eid:
        raise HTTPException(400, "employee_id 不能为空")
    sf = get_session_factory()
    with sf() as session:
        rows = list_employees_exec()
        index = {str(r.get("id") or "").strip(): r for r in rows if str(r.get("id") or "").strip()}
        row = index.get(eid)
        if not row:
            raise HTTPException(404, "员工不存在")
        provider_map = _build_provider_status_map(session, int(admin_user.id))
        manifest_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        return _analyze_employee_capability(
            session,
            user_id=int(admin_user.id),
            employee_row=row,
            provider_status_map=provider_map,
            fernet_ok=fernet_configured(),
            manifest_cache=manifest_cache,
        )


@router.post("/employees/execution-capabilities")
def post_employee_execution_capabilities(
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    ids_raw = body.get("employee_ids")
    employee_ids: List[str] = []
    if isinstance(ids_raw, list):
        for x in ids_raw:
            sid = _as_str(x)
            if sid and sid not in employee_ids:
                employee_ids.append(sid)
    sf = get_session_factory()
    with sf() as session:
        rows = list_employees_exec()
        index = {str(r.get("id") or "").strip(): r for r in rows if str(r.get("id") or "").strip()}
        if not employee_ids:
            employee_ids = sorted(index.keys())
        provider_map = _build_provider_status_map(session, int(admin_user.id))
        fernet_ok = fernet_configured()
        manifest_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        items: List[Dict[str, Any]] = []
        for eid in employee_ids:
            row = index.get(eid)
            if not row:
                items.append(
                    {
                        "employee_id": eid,
                        "name": eid,
                        "source": "unknown",
                        "deployed": False,
                        "executable": False,
                        "reasons": ["员工不存在"],
                        "handlers": [],
                        "declared_dependencies": [],
                        "llm": {
                            "provider": "auto",
                            "model": "auto",
                            "needs_llm": False,
                            "activated": False,
                            "key_source": "none",
                        },
                        "risk": {"high_risk": False, "requires_confirmation": False, "details": []},
                        "recent_execution": None,
                        "recent_ops_audits": [],
                    }
                )
                continue
            items.append(
                _analyze_employee_capability(
                    session,
                    user_id=int(admin_user.id),
                    employee_row=row,
                    provider_status_map=provider_map,
                    fernet_ok=fernet_ok,
                    manifest_cache=manifest_cache,
                )
            )
    return {"items": items, "count": len(items)}


@router.get("/duty-graph/no-key-employees")
def get_duty_graph_no_key_employees(
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """列出当前管理员账户视角下「需要 LLM 但无可用密钥」的员工。

    返回中的 ``suggested_action`` 给前端做引导：

    - ``align_to_auto`` —— 当前员工 manifest 写死了某个 provider，但账户里有其他可用密钥，建议把员工改成 ``auto/auto``；
    - ``add_account_key`` —— 已经是 ``auto``（或所有 provider 都没钥匙），只能去凭据页加密钥。
    """
    sf = get_session_factory()
    with sf() as session:
        rows = list_employees_exec()
        index = {str(r.get("id") or "").strip(): r for r in rows if str(r.get("id") or "").strip()}
        provider_map = _build_provider_status_map(session, int(admin_user.id))
        fernet_ok = fernet_configured()
        any_provider_ok = any(
            _provider_has_usable_key(row, fernet_ok) for row in provider_map.values()
        )
        manifest_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        items: List[Dict[str, Any]] = []
        for eid in sorted(index.keys()):
            row = index[eid]
            cap = _analyze_employee_capability(
                session,
                user_id=int(admin_user.id),
                employee_row=row,
                provider_status_map=provider_map,
                fernet_ok=fernet_ok,
                manifest_cache=manifest_cache,
            )
            llm = cap.get("llm") or {}
            if not bool(llm.get("needs_llm")):
                continue
            if bool(llm.get("activated")):
                continue
            cur_provider = _as_str(llm.get("provider")).lower()
            cur_model = _as_str(llm.get("model"))
            is_auto = cur_provider == "auto" or cur_model.lower() == "auto"
            if is_auto or not any_provider_ok:
                suggested_action = "add_account_key"
            else:
                suggested_action = "align_to_auto"
            items.append(
                {
                    "pkg_id": eid,
                    "name": cap.get("name") or eid,
                    "current_provider": cur_provider or "(empty)",
                    "current_model": cur_model,
                    "key_source": _as_str(llm.get("key_source")) or "none",
                    "suggested_action": suggested_action,
                    "reasons": cap.get("reasons") or [],
                }
            )
        return {
            "items": items,
            "count": len(items),
            "fernet_configured": fernet_ok,
            "any_provider_has_key": any_provider_ok,
        }


def execute_duty_graph_programmatic(
    *,
    target_employee_id: str,
    task: str,
    input_data: Dict[str, Any],
    created_by_user_id: int,
    include_dependencies: bool = True,
    max_concurrency: int = 2,
    allow_high_risk_real_run: bool = False,
    bench_llm_override: Optional[Tuple[str, str]] = None,
    bench_llm_target_id: str = "daily-orchestrator",
) -> Dict[str, Any]:
    """在岗协作图执行（供定时任务 / orchestrator 调用）。失败返回 ``{"ok": False, "error": ...}``。"""
    target = _as_str(target_employee_id)
    task_s = _as_str(task)
    if not target:
        return {"ok": False, "error": "target_employee_id 不能为空"}
    if not task_s:
        return {"ok": False, "error": "task 不能为空"}
    max_concurrency = max(1, min(max_concurrency, 4))

    raw_input = input_data or {}
    if not isinstance(raw_input, dict):
        return {"ok": False, "error": "input_data 必须是对象"}
    if len(_json_dumps(raw_input)) > _MAX_RUN_INPUT_BYTES:
        return {"ok": False, "error": "input_data 过大"}

    sf = get_session_factory()
    with sf() as session:
        rows = list_employees_exec()
        employee_index = {
            str(r.get("id") or "").strip(): r for r in rows if str(r.get("id") or "").strip()
        }
        if target not in employee_index:
            return {"ok": False, "error": "目标员工不存在"}

        provider_map = _build_provider_status_map(session, int(created_by_user_id))
        fernet_ok = fernet_configured()
        manifest_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        deps_map: Dict[str, List[str]] = {}
        missing_dep_map: Dict[str, List[str]] = {}

        def _deps_for(eid: str) -> List[str]:
            if eid in deps_map:
                return deps_map[eid]
            manifest = _load_manifest_for_employee(session, eid, employee_index, manifest_cache)
            if not isinstance(manifest, dict):
                deps_map[eid] = []
                return deps_map[eid]
            deps_map[eid] = _extract_manifest_dependencies(manifest)
            return deps_map[eid]

        selected: Set[str] = {target}
        if include_dependencies:
            queue = [target]
            while queue:
                cur = queue.pop(0)
                for dep in _deps_for(cur):
                    if dep in employee_index:
                        if dep not in selected:
                            selected.add(dep)
                            queue.append(dep)
                    else:
                        missing_dep_map.setdefault(cur, []).append(dep)

        order, cycle_nodes = _topo_sort(selected, deps_map)
        if cycle_nodes:
            return {"ok": False, "error": f"依赖图存在循环：{', '.join(cycle_nodes)}"}

        run = DutyGraphRun(
            created_by_user_id=int(created_by_user_id),
            target_employee_id=target,
            task=task_s,
            input_data_json=_json_dumps(raw_input),
            include_dependencies=include_dependencies,
            max_concurrency=max_concurrency,
            allow_high_risk_real_run=allow_high_risk_real_run,
            status="running",
            total_nodes=len(order),
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        session.flush()
        run_id = int(run.id)

        for idx, eid in enumerate(order):
            session.add(
                DutyGraphRunNode(
                    run_id=run_id,
                    employee_id=eid,
                    order_index=idx,
                    depends_on_json=_json_dumps(sorted(d for d in _deps_for(eid) if d in selected)),
                    status="pending",
                )
            )
        session.commit()

        node_status: Dict[str, str] = {}
        first_error = ""
        runtime = get_default_employee_client()

        # 按拓扑层分组：layer[i] 中的节点彼此无依赖，可并行
        layer_index: Dict[str, int] = {}
        for eid in order:
            d = (
                _json_loads(
                    _json_dumps(deps_map.get(eid, [])),
                    [],
                )
                if False
                else deps_map.get(eid, [])
            )
            relevant = [x for x in (d or []) if x in selected]
            layer_index[eid] = (
                (max((layer_index[x] for x in relevant), default=-1) + 1) if relevant else 0
            )
        layers: Dict[int, List[str]] = {}
        for eid, lvl in layer_index.items():
            layers.setdefault(lvl, []).append(eid)

        from concurrent.futures import ThreadPoolExecutor
        from threading import Lock

        status_lock = Lock()
        error_lock = Lock()

        def _execute_one(eid: str) -> None:
            nonlocal first_error
            sf2 = get_session_factory()
            with sf2() as sess2:
                node = (
                    sess2.query(DutyGraphRunNode)
                    .filter(DutyGraphRunNode.run_id == run_id, DutyGraphRunNode.employee_id == eid)
                    .first()
                )
                if not node:
                    return
                deps_local = _json_loads(node.depends_on_json or "[]", [])
                with status_lock:
                    blocked = [d for d in deps_local if node_status.get(d) not in ("success",)]
                if blocked:
                    node.status = "skipped"
                    node.error = f"上游未成功：{', '.join(blocked)}"
                    node.completed_at = datetime.now(timezone.utc)
                    sess2.commit()
                    with status_lock:
                        node_status[eid] = "skipped"
                    return
                missing = missing_dep_map.get(eid) or []
                if missing:
                    node.status = "skipped"
                    node.error = f"缺少依赖员工：{', '.join(missing)}"
                    node.completed_at = datetime.now(timezone.utc)
                    sess2.commit()
                    with status_lock:
                        node_status[eid] = "skipped"
                    return

                cap = _analyze_employee_capability(
                    sess2,
                    user_id=int(created_by_user_id),
                    employee_row=employee_index[eid],
                    provider_status_map=provider_map,
                    fernet_ok=fernet_ok,
                    manifest_cache=manifest_cache,
                )
                if not bool(cap.get("executable")):
                    reasons = cap.get("reasons") if isinstance(cap.get("reasons"), list) else []
                    node.status = "skipped"
                    node.error = (
                        "；".join(_as_str(r) for r in reasons if _as_str(r)) or "员工当前不可执行"
                    )
                    node.summary = "capability blocked"
                    node.completed_at = datetime.now(timezone.utc)
                    node.result_json = _json_dumps({"capability": cap}, max_chars=3000)
                    sess2.commit()
                    with status_lock:
                        node_status[eid] = "skipped"
                    return
                if bool(cap.get("risk", {}).get("high_risk")) and not allow_high_risk_real_run:
                    node.status = "skipped"
                    node.error = "高风险动作未确认（allow_high_risk_real_run=false）"
                    node.summary = "confirmation required"
                    node.completed_at = datetime.now(timezone.utc)
                    node.result_json = _json_dumps({"capability": cap}, max_chars=3000)
                    sess2.commit()
                    with status_lock:
                        node_status[eid] = "skipped"
                    return

                node.status = "running"
                node.started_at = datetime.now(timezone.utc)
                sess2.commit()

            t0 = time.perf_counter()
            result: Dict[str, Any] = {}
            error_text = ""
            status = "success"
            llm_tokens = 0
            duration_ms = 0.0
            exec_kw: Dict[str, Any] = {}
            if bench_llm_override is not None and eid == bench_llm_target_id:
                exec_kw["bench_llm_override"] = bench_llm_override
            try:
                run_res = runtime.execute_task(
                    employee_id=eid,
                    task=task_s,
                    input_data=raw_input,
                    user_id=int(created_by_user_id),
                    **exec_kw,
                )
                result = run_res if isinstance(run_res, dict) else {"result": run_res}
                llm_tokens = int(result.get("llm_tokens") or 0)
                duration_ms = float(result.get("duration_ms") or 0.0)
                if duration_ms <= 0:
                    duration_ms = round((time.perf_counter() - t0) * 1000, 3)
            except Exception as exc:  # noqa: BLE001
                status = "failed"
                error_text = str(exc)
                duration_ms = round((time.perf_counter() - t0) * 1000, 3)
                result = {"error": error_text}

            sf3 = get_session_factory()
            with sf3() as sess3:
                node = (
                    sess3.query(DutyGraphRunNode)
                    .filter(DutyGraphRunNode.run_id == run_id, DutyGraphRunNode.employee_id == eid)
                    .first()
                )
                if not node:
                    return
                metric = (
                    sess3.query(EmployeeExecutionMetric)
                    .filter(
                        EmployeeExecutionMetric.employee_id == eid,
                        EmployeeExecutionMetric.user_id == int(created_by_user_id),
                    )
                    .order_by(EmployeeExecutionMetric.id.desc())
                    .first()
                )
                node.metric_id = int(metric.id) if metric else None
                node.status = status
                node.completed_at = datetime.now(timezone.utc)
                node.duration_ms = duration_ms
                node.llm_tokens = llm_tokens
                node.error = error_text[:2000]
                node.summary = (
                    _as_str(result.get("result", ""))[:1000] if isinstance(result, dict) else ""
                )
                node.result_json = _json_dumps(result, max_chars=_MAX_RESULT_BYTES)
                sess3.commit()
            with status_lock:
                node_status[eid] = status
            if status == "failed":
                with error_lock:
                    if not first_error:
                        first_error = error_text[:1000] or f"{eid} 执行失败"

        # 该 with 块中此前持有的 session 已不再被节点循环使用，提交后释放
        session.commit()
        for lvl in sorted(layers.keys()):
            layer_eids = layers[lvl]
            if max_concurrency <= 1 or len(layer_eids) == 1:
                for eid in layer_eids:
                    _execute_one(eid)
            else:
                with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
                    list(pool.map(_execute_one, layer_eids))

        run_row = session.get(DutyGraphRun, run_id)
        if not run_row:
            return {"ok": False, "error": "运行记录丢失"}
        rows2 = session.query(DutyGraphRunNode).filter(DutyGraphRunNode.run_id == run_id).all()
        success_count = len([r for r in rows2 if r.status == "success"])
        failed_count = len([r for r in rows2 if r.status == "failed"])
        skipped_count = len([r for r in rows2 if r.status == "skipped"])
        run_row.success_count = success_count
        run_row.failed_count = failed_count
        run_row.skipped_count = skipped_count
        run_row.status = "failed" if failed_count > 0 else "completed"
        run_row.error = first_error
        run_row.completed_at = datetime.now(timezone.utc)
        session.commit()
        out = _serialize_run(session, run_id)
        out["ok"] = True
        return out


@router.post("/duty-graph/runs")
def create_duty_graph_run(
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    target = _as_str(body.get("target_employee_id"))
    task = _as_str(body.get("task"))
    include_dependencies = bool(body.get("include_dependencies", True))
    allow_high_risk_real_run = bool(body.get("allow_high_risk_real_run", False))
    if not target:
        raise HTTPException(400, "target_employee_id 不能为空")
    if not task:
        raise HTTPException(400, "task 不能为空")
    try:
        max_concurrency = int(body.get("max_concurrency", 2))
    except (TypeError, ValueError):
        max_concurrency = 2

    raw_input = body.get("input_data", {})
    if raw_input is None:
        raw_input = {}
    if not isinstance(raw_input, dict):
        raise HTTPException(400, "input_data 必须是对象")
    if len(_json_dumps(raw_input)) > _MAX_RUN_INPUT_BYTES:
        raise HTTPException(400, "input_data 过大")

    out = execute_duty_graph_programmatic(
        target_employee_id=target,
        task=task,
        input_data=raw_input,
        created_by_user_id=int(admin_user.id),
        include_dependencies=include_dependencies,
        max_concurrency=max_concurrency,
        allow_high_risk_real_run=allow_high_risk_real_run,
        bench_llm_override=None,
    )
    if not out.get("ok"):
        msg = _as_str(out.get("error")) or "duty graph failed"
        code = 404 if "不存在" in msg else 400
        raise HTTPException(code, msg)
    out.pop("ok", None)
    return out


@router.get("/duty-graph/runs/{run_id}")
def get_duty_graph_run(
    run_id: int,
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _ = admin_user
    if run_id <= 0:
        raise HTTPException(400, "run_id 非法")
    sf = get_session_factory()
    with sf() as session:
        return _serialize_run(session, run_id)


@router.get("/duty-graph/health")
def duty_graph_health(
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """全员自治闭环健康看板：缺岗、调度器、待审 CR、未识别事件等。"""
    _ = admin_user
    out: Dict[str, Any] = {"ok": True}

    # 编制 ↔ 已上架员工包
    try:
        from modstore_server.duty_roster import YUANGON_AREAS, all_planned_employee_ids
        from modstore_server.models import CatalogItem

        sf = get_session_factory()
        with sf() as session:
            registered = {
                str(r[0])
                for r in session.query(CatalogItem.pkg_id)
                .filter(CatalogItem.artifact == "employee_pack")
                .all()
                if r[0]
            }
        planned = set(all_planned_employee_ids())
        out["staffing"] = {
            "planned_count": len(planned),
            "registered_count": len(planned & registered),
            "missing_employees": sorted(planned - registered),
            "extra_employees": sorted(registered - planned),
            "areas": [
                {
                    "key": k,
                    "label": v.get("label", k),
                    "missing": sorted(set(v.get("ids") or []) - registered),
                }
                for k, v in YUANGON_AREAS.items()
            ],
        }
    except Exception as exc:
        logger.exception("staffing summary failed")
        out["staffing"] = {"error": str(exc)}

    # 调度器：员工 cron 注册情况
    try:
        from modstore_server.workflow_scheduler import list_employee_cron_jobs

        out["employee_cron_jobs"] = list_employee_cron_jobs()
    except Exception as exc:
        out["employee_cron_jobs"] = []
        out["employee_cron_jobs_error"] = str(exc)

    # 待审 CR
    try:
        from modstore_server.models import EmployeeChangeRequest

        sf = get_session_factory()
        with sf() as session:
            pending = (
                session.query(EmployeeChangeRequest)
                .filter(EmployeeChangeRequest.status == "pending")
                .count()
            )
            failed = (
                session.query(EmployeeChangeRequest)
                .filter(EmployeeChangeRequest.status == "failed")
                .count()
            )
        out["change_requests"] = {"pending": int(pending), "failed": int(failed)}
    except Exception as exc:
        out["change_requests"] = {"error": str(exc)}

    # 未注册事件类型
    try:
        from datetime import timedelta

        from modstore_server.models import IncidentEvent

        sf = get_session_factory()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        with sf() as session:
            unknown = (
                session.query(IncidentEvent)
                .filter(
                    IncidentEvent.event_type == "incident.unknown",
                    IncidentEvent.created_at >= cutoff,
                )
                .count()
            )
        out["incident_unknown_24h"] = int(unknown)
    except Exception as exc:
        out["incident_unknown_24h"] = 0
        out["incident_unknown_error"] = str(exc)

    # 编排开关
    try:
        out["env_flags"] = {
            "MODSTORE_DAILY_ORCHESTRATOR_ENABLED": os.environ.get(
                "MODSTORE_DAILY_ORCHESTRATOR_ENABLED", "0"
            ),
            "MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED": os.environ.get(
                "MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED", "1"
            ),
            "MODSTORE_AUTO_APPROVE_ENABLED": os.environ.get("MODSTORE_AUTO_APPROVE_ENABLED", "0"),
            "MODSTORE_CR_GIT_BRANCH_ENABLED": os.environ.get("MODSTORE_CR_GIT_BRANCH_ENABLED", "1"),
        }
    except Exception:
        pass

    return out
