# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.admin_duty_graph_api")


def _json_dumps(obj: _facade().Any, *, max_chars: int = 0) -> str:
    text = _facade().json.dumps(obj, ensure_ascii=False)
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "…"
    return text


def _json_loads(text: str, default: _facade().Any) -> _facade().Any:
    raw = (text or "").strip()
    if not raw:
        return default
    try:
        return _facade().json.loads(raw)
    except _facade().json.JSONDecodeError:
        return default


def _as_str(v: _facade().Any) -> str:
    return str(v or "").strip()


def _extract_manifest_dependencies(
    manifest: _facade().Mapping[str, _facade().Any]
) -> _facade().List[str]:
    """Collaboration-only deps for duty-graph execution order.

    Reads only ``depends_on`` and ``employee_config_v2.collaboration.depends_on``.
    Ignores ``release_hints`` / ``references`` (infra pointers); deploy topology lives in
    ``MODstore_deploy/orchestration/*.yaml``, not in manifest edges.
    """
    deps: _facade().List[str] = []
    root = manifest if isinstance(manifest, _facade().Mapping) else {}
    root_dep = root.get("depends_on")
    if isinstance(root_dep, list):
        deps.extend((_facade()._as_str(d) for d in root_dep))
    v2 = root.get("employee_config_v2")
    if isinstance(v2, _facade().Mapping):
        collab = v2.get("collaboration")
        if isinstance(collab, _facade().Mapping):
            raw = collab.get("depends_on")
            if isinstance(raw, list):
                deps.extend((_facade()._as_str(d) for d in raw))
    seen: _facade().Set[str] = set()
    out: _facade().List[str] = []
    for d in deps:
        if not d or d in seen:
            continue
        seen.add(d)
        out.append(d)
    return out


def _clean_handlers(actions_cfg: _facade().Mapping[str, _facade().Any]) -> _facade().List[str]:
    handlers_raw = actions_cfg.get("handlers")
    if not isinstance(handlers_raw, list):
        return ["echo"]
    out: _facade().List[str] = []
    for h in handlers_raw:
        hs = _facade()._as_str(h)
        if hs:
            out.append(hs)
    return out or ["echo"]


def _provider_has_usable_key(
    row: _facade().Mapping[str, _facade().Any] | None, fernet_ok: bool
) -> bool:
    if not row:
        return False
    if bool(row.get("has_platform_key")):
        return True
    if bool(row.get("has_user_override")) and fernet_ok:
        return True
    return False


def _build_provider_status_map(
    session: _facade().Session, user_id: int
) -> _facade().Dict[str, _facade().Dict[str, _facade().Any]]:
    out: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    for provider in _facade().KNOWN_PROVIDERS:
        out[provider] = _facade().credential_status(session, int(user_id), provider)
    return out


def _resolve_llm_state(
    *,
    handlers: _facade().Sequence[str],
    config: _facade().Mapping[str, _facade().Any],
    provider_status_map: _facade().Mapping[str, _facade().Mapping[str, _facade().Any]],
    fernet_ok: bool,
) -> _facade().Dict[str, _facade().Any]:
    needs_llm = any((_facade()._as_str(h) not in _facade()._LLM_FREE_HANDLERS for h in handlers))
    cog = config.get("cognition") if isinstance(config.get("cognition"), _facade().Mapping) else {}
    agent = (
        cog.get("agent")
        if isinstance(cog, _facade().Mapping) and isinstance(cog.get("agent"), _facade().Mapping)
        else {}
    )
    model_cfg = (
        agent.get("model")
        if isinstance(agent, _facade().Mapping)
        and isinstance(agent.get("model"), _facade().Mapping)
        else {}
    )
    provider = _facade()._as_str(model_cfg.get("provider")) or "auto"
    model_name = _facade()._as_str(model_cfg.get("model_name")) or "auto"
    is_auto = provider.lower() == "auto" or model_name.lower() == "auto"
    if is_auto:
        any_ok = any(
            (
                _facade()._provider_has_usable_key(row, fernet_ok)
                for row in provider_status_map.values()
            )
        )
        activated = not needs_llm or any_ok
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
        "activated": not needs_llm or credential_ok,
        "key_source": "byok" if has_byok else "platform" if has_platform else "none",
    }


def _detect_risk(
    actions_cfg: _facade().Mapping[str, _facade().Any], handlers: _facade().Sequence[str]
) -> _facade().Dict[str, _facade().Any]:
    details: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for raw in handlers:
        handler = _facade()._as_str(raw)
        if not handler or handler not in _facade()._HIGH_RISK_HANDLERS:
            continue
        entry: _facade().Dict[str, _facade().Any] = {"handler": handler}
        if handler in ("shell_exec", "ssh_exec"):
            block = (
                actions_cfg.get(handler)
                if isinstance(actions_cfg.get(handler), _facade().Mapping)
                else {}
            )
            command_id = _facade()._as_str(block.get("command_id"))
            spec = _facade().OPS_COMMAND_REGISTRY.get(command_id)
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
    return {"high_risk": bool(details), "requires_confirmation": bool(details), "details": details}


def _latest_metric(
    session: _facade().Session, employee_id: str
) -> _facade().Dict[str, _facade().Any] | None:
    row = (
        session.query(_facade().EmployeeExecutionMetric)
        .filter(_facade().EmployeeExecutionMetric.employee_id == employee_id)
        .order_by(_facade().EmployeeExecutionMetric.id.desc())
        .first()
    )
    if not row:
        return None
    created_at_epoch = 0.0
    if row.created_at:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=_facade().timezone.utc)
        created_at_epoch = created_at.timestamp()
    return {
        "id": int(row.id),
        "status": _facade()._as_str(row.status),
        "task": _facade()._as_str(row.task),
        "duration_ms": float(row.duration_ms or 0.0),
        "llm_tokens": int(row.llm_tokens or 0),
        "error": _facade()._as_str(row.error),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_at_epoch": created_at_epoch,
    }


def _latest_ops_audits(
    session: _facade().Session, employee_id: str, limit: int = 5
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    rows = (
        session.query(_facade().OpsActionAuditLog)
        .filter(_facade().OpsActionAuditLog.employee_id == employee_id)
        .order_by(_facade().OpsActionAuditLog.id.desc())
        .limit(max(1, min(limit, 20)))
        .all()
    )
    return [
        {
            "id": int(r.id),
            "handler": _facade()._as_str(r.handler),
            "command_id": _facade()._as_str(r.command_id),
            "exit_code": r.exit_code,
            "dry_run": bool(r.dry_run),
            "approval_required": bool(r.approval_required),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def _load_manifest_for_employee(
    session: _facade().Session,
    employee_id: str,
    employee_index: _facade().Mapping[str, _facade().Mapping[str, _facade().Any]],
    manifest_cache: _facade().MutableMapping[
        str, _facade().Optional[_facade().Dict[str, _facade().Any]]
    ],
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    if employee_id in manifest_cache:
        return manifest_cache[employee_id]
    row = employee_index.get(employee_id) or {}
    if _facade()._as_str(row.get("source")) == "v1_catalog":
        manifest_cache[employee_id] = None
        return None
    try:
        pack = _facade().load_employee_pack(session, employee_id)
        manifest = pack.get("manifest") if isinstance(pack, _facade().Mapping) else {}
        manifest_cache[employee_id] = manifest if isinstance(manifest, dict) else {}
    except Exception:
        manifest_cache[employee_id] = None
    return manifest_cache[employee_id]


def _analyze_employee_capability(
    session: _facade().Session,
    *,
    user_id: int,
    employee_row: _facade().Mapping[str, _facade().Any],
    provider_status_map: _facade().Mapping[str, _facade().Mapping[str, _facade().Any]],
    fernet_ok: bool,
    manifest_cache: _facade().MutableMapping[
        str, _facade().Optional[_facade().Dict[str, _facade().Any]]
    ],
) -> _facade().Dict[str, _facade().Any]:
    employee_id = _facade()._as_str(employee_row.get("id"))
    source = _facade()._as_str(employee_row.get("source")) or "catalog"
    base: _facade().Dict[str, _facade().Any] = {
        "employee_id": employee_id,
        "name": _facade()._as_str(employee_row.get("name")) or employee_id,
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
        "runtime_issues": [],
        "operational_state": "unknown",
        "pack_updated_at_epoch": 0.0,
        "recent_execution": _facade()._latest_metric(session, employee_id),
        "recent_ops_audits": _facade()._latest_ops_audits(session, employee_id, 5),
    }
    if source == "v1_catalog":
        base["reasons"] = ["仅目录登记（v1_catalog），未入库为可执行 employee_pack"]
        return base
    manifest = _facade()._load_manifest_for_employee(
        session, employee_id, {employee_id: employee_row}, manifest_cache
    )
    if not isinstance(manifest, dict):
        base["reasons"] = ["无法读取员工包 manifest"]
        return base
    cfg = _facade().parse_employee_config_v2(manifest)
    actions_cfg = cfg.get("actions") if isinstance(cfg.get("actions"), _facade().Mapping) else {}
    handlers = _facade()._clean_handlers(actions_cfg)
    deps = _facade()._extract_manifest_dependencies(manifest)
    llm_state = _facade()._resolve_llm_state(
        handlers=handlers, config=cfg, provider_status_map=provider_status_map, fernet_ok=fernet_ok
    )
    risk_state = _facade()._detect_risk(actions_cfg, handlers)
    reasons: _facade().List[str] = []
    if llm_state.get("needs_llm") and (not llm_state.get("activated")):
        reasons.append("缺少可用 LLM 密钥（平台密钥或可解密 BYOK）")
    try:
        loaded_pack = _facade().load_employee_pack(session, employee_id)
        runtime_issues = _facade().employee_pack_runtime_issues(loaded_pack)
    except Exception as exc:
        loaded_pack = {}
        runtime_issues = [f"员工包运行时检查失败: {str(exc)[:300]}"]
    reasons.extend(runtime_issues)
    recent = base.get("recent_execution")
    pack_updated_at = float(loaded_pack.get("archive_mtime") or 0.0)
    if (
        not isinstance(recent, _facade().Mapping)
        or float(recent.get("created_at_epoch") or 0.0) < pack_updated_at
    ):
        operational_state = "untested"
    elif _facade()._as_str(recent.get("status")) == "success":
        operational_state = "healthy"
    else:
        operational_state = "degraded"
    base.update(
        {
            "handlers": handlers,
            "declared_dependencies": deps,
            "llm": llm_state,
            "risk": risk_state,
            "runtime_issues": runtime_issues,
            "operational_state": operational_state,
            "pack_updated_at_epoch": pack_updated_at,
            "reasons": reasons,
            "executable": len(reasons) == 0,
        }
    )
    return base


def _topo_sort(
    nodes: _facade().Iterable[str], deps_map: _facade().Mapping[str, _facade().Sequence[str]]
) -> _facade().Tuple[_facade().List[str], _facade().List[str]]:
    """Kahn's algorithm with cycle-breaking.

    Returns (topological_order, broken_cycle_nodes). When a cycle is
    detected, the remaining nodes are appended in sorted order so the caller
    can proceed instead of hard-failing. ``broken_cycle_nodes`` lists the
    nodes that were part of a cycle (non-empty only when a cycle existed).
    """
    node_set = set(nodes)
    indeg: _facade().Dict[str, int] = {n: 0 for n in node_set}
    children: _facade().Dict[str, _facade().List[str]] = {n: [] for n in node_set}
    for node in node_set:
        for dep in deps_map.get(node) or []:
            if dep not in node_set:
                continue
            indeg[node] += 1
            children[dep].append(node)
    queue: _facade().List[str] = sorted((n for (n, deg) in indeg.items() if deg == 0))
    out: _facade().List[str] = []
    while queue:
        cur = queue.pop(0)
        out.append(cur)
        for child in children.get(cur) or []:
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)
                queue.sort()
    if len(out) == len(node_set):
        return (out, [])
    cycle_nodes = sorted((n for (n, deg) in indeg.items() if deg > 0))
    out.extend(cycle_nodes)
    return (out, cycle_nodes)


def _serialize_run(session: _facade().Session, run_id: int) -> _facade().Dict[str, _facade().Any]:
    run = session.get(_facade().DutyGraphRun, int(run_id))
    if not run:
        raise _facade().HTTPException(404, "运行记录不存在")
    rows = (
        session.query(_facade().DutyGraphRunNode)
        .filter(_facade().DutyGraphRunNode.run_id == run.id)
        .order_by(_facade().DutyGraphRunNode.order_index.asc(), _facade().DutyGraphRunNode.id.asc())
        .all()
    )
    items = []
    for r in rows:
        items.append(
            {
                "id": int(r.id),
                "employee_id": _facade()._as_str(r.employee_id),
                "order_index": int(r.order_index or 0),
                "depends_on": _facade()._json_loads(r.depends_on_json or "[]", []),
                "status": _facade()._as_str(r.status),
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_ms": float(r.duration_ms or 0.0),
                "llm_tokens": int(r.llm_tokens or 0),
                "metric_id": int(r.metric_id) if r.metric_id else None,
                "summary": _facade()._as_str(r.summary),
                "error": _facade()._as_str(r.error),
                "result": _facade()._json_loads(r.result_json or "{}", {}),
            }
        )
    return {
        "id": int(run.id),
        "created_by_user_id": int(run.created_by_user_id),
        "target_employee_id": _facade()._as_str(run.target_employee_id),
        "task": _facade()._as_str(run.task),
        "input_data": _facade()._json_loads(run.input_data_json or "{}", {}),
        "include_dependencies": bool(run.include_dependencies),
        "max_concurrency": int(run.max_concurrency or 1),
        "allow_high_risk_real_run": bool(run.allow_high_risk_real_run),
        "status": _facade()._as_str(run.status),
        "total_nodes": int(run.total_nodes or 0),
        "success_count": int(run.success_count or 0),
        "failed_count": int(run.failed_count or 0),
        "skipped_count": int(run.skipped_count or 0),
        "error": _facade()._as_str(run.error),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "nodes": items,
    }


@_facade().router.get("/employees/{employee_id}/execution-capability")
def get_employee_execution_capability(
    employee_id: str, admin_user: _facade().User = _facade().Depends(_facade().require_admin)
) -> _facade().Dict[str, _facade().Any]:
    _ = admin_user
    eid = _facade()._as_str(employee_id)
    if not eid:
        raise _facade().HTTPException(400, "employee_id 不能为空")
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = _facade().list_employees_exec()
        index = {
            _facade().norm_pkg_id(r.get("id")): r
            for r in rows
            if _facade().norm_pkg_id(r.get("id"))
        }
        row = index.get(_facade().norm_pkg_id(eid))
        if not row:
            raise _facade().HTTPException(404, "员工未部署（执行库未注册）")
        provider_map = _facade()._build_provider_status_map(session, int(admin_user.id))
        manifest_cache: _facade().Dict[
            str, _facade().Optional[_facade().Dict[str, _facade().Any]]
        ] = {}
        return _facade()._analyze_employee_capability(
            session,
            user_id=int(admin_user.id),
            employee_row=row,
            provider_status_map=provider_map,
            fernet_ok=_facade().fernet_configured(),
            manifest_cache=manifest_cache,
        )


@_facade().router.post("/employees/execution-capabilities")
def post_employee_execution_capabilities(
    body: _facade().Dict[str, _facade().Any] = _facade().Body(default_factory=dict),
    admin_user: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    ids_raw = body.get("employee_ids")
    employee_ids: _facade().List[str] = []
    if isinstance(ids_raw, list):
        for x in ids_raw:
            sid = _facade()._as_str(x)
            if sid and sid not in employee_ids:
                employee_ids.append(sid)
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = _facade().list_employees_exec()
        index = {
            _facade().norm_pkg_id(r.get("id")): r
            for r in rows
            if _facade().norm_pkg_id(r.get("id"))
        }
        if not employee_ids:
            employee_ids = sorted(index.keys())
        provider_map = _facade()._build_provider_status_map(session, int(admin_user.id))
        fernet_ok = _facade().fernet_configured()
        manifest_cache: _facade().Dict[
            str, _facade().Optional[_facade().Dict[str, _facade().Any]]
        ] = {}
        items: _facade().List[_facade().Dict[str, _facade().Any]] = []
        for eid in employee_ids:
            row = index.get(_facade().norm_pkg_id(eid))
            if not row:
                items.append(
                    {
                        "employee_id": eid,
                        "name": eid,
                        "source": "unknown",
                        "deployed": False,
                        "executable": False,
                        "reasons": ["员工未部署（执行库未注册）"],
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
                _facade()._analyze_employee_capability(
                    session,
                    user_id=int(admin_user.id),
                    employee_row=row,
                    provider_status_map=provider_map,
                    fernet_ok=fernet_ok,
                    manifest_cache=manifest_cache,
                )
            )
    return {"items": items, "count": len(items)}


@_facade().router.get("/duty-graph/no-key-employees")
def get_duty_graph_no_key_employees(
    admin_user: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    """列出当前管理员账户视角下「需要 LLM 但无可用密钥」的员工。

    返回中的 ``suggested_action`` 给前端做引导：

    - ``align_to_auto`` —— 当前员工 manifest 写死了某个 provider，但账户里有其他可用密钥，建议把员工改成 ``auto/auto``；
    - ``add_account_key`` —— 已经是 ``auto``（或所有 provider 都没钥匙），只能去凭据页加密钥。
    """
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = _facade().list_employees_exec()
        index = {
            _facade().norm_pkg_id(r.get("id")): r
            for r in rows
            if _facade().norm_pkg_id(r.get("id"))
        }
        provider_map = _facade()._build_provider_status_map(session, int(admin_user.id))
        fernet_ok = _facade().fernet_configured()
        any_provider_ok = any(
            (_facade()._provider_has_usable_key(row, fernet_ok) for row in provider_map.values())
        )
        manifest_cache: _facade().Dict[
            str, _facade().Optional[_facade().Dict[str, _facade().Any]]
        ] = {}
        items: _facade().List[_facade().Dict[str, _facade().Any]] = []
        for eid in sorted(index.keys()):
            row = index[eid]
            cap = _facade()._analyze_employee_capability(
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
            cur_provider = _facade()._as_str(llm.get("provider")).lower()
            cur_model = _facade()._as_str(llm.get("model"))
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
                    "key_source": _facade()._as_str(llm.get("key_source")) or "none",
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
