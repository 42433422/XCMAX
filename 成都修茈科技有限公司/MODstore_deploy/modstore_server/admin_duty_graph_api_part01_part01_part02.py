# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.admin_duty_graph_api")


def _serialize_run(session: _facade().Session, run_id: int) -> _facade().Dict[str, _facade().Any]:
    run = session.get(_facade().DutyGraphRun, int(run_id))
    if not run:
        raise _facade().HTTPException(404, "运行记录不存在")
    rows = (
        session.query(_facade().DutyGraphRunNode)
        .filter(_facade().DutyGraphRunNode.run_id == run.id)
        .order_by(
            _facade().DutyGraphRunNode.order_index.asc(),
            _facade().DutyGraphRunNode.id.asc(),
        )
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
    employee_id: str,
    admin_user: _facade().User = _facade().Depends(_facade().require_admin),
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
                        "risk": {
                            "high_risk": False,
                            "requires_confirmation": False,
                            "details": [],
                        },
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
