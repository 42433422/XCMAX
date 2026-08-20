# mypy: disable-error-code="attr-defined, call-overload, no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.admin_duty_graph_api")


def execute_duty_graph_programmatic(
    *,
    target_employee_id: str,
    task: str,
    input_data: _facade().Dict[str, _facade().Any],
    created_by_user_id: int,
    include_dependencies: bool = True,
    max_concurrency: int = 2,
    allow_high_risk_real_run: bool = False,
    bench_llm_override: _facade().Optional[_facade().Tuple[str, str]] = None,
    bench_llm_target_id: str = "daily-orchestrator",
) -> _facade().Dict[str, _facade().Any]:
    """在岗协作图执行（供定时任务 / orchestrator 调用）。失败返回 ``{"ok": False, "error": ...}``。"""
    target = _facade()._as_str(target_employee_id)
    task_s = _facade()._as_str(task)
    if not target:
        return {"ok": False, "error": "target_employee_id 不能为空"}
    if not task_s:
        return {"ok": False, "error": "task 不能为空"}
    max_concurrency = max(1, min(max_concurrency, 4))
    raw_input = input_data or {}
    if not isinstance(raw_input, dict):
        return {"ok": False, "error": "input_data 必须是对象"}
    if len(_facade()._json_dumps(raw_input)) > _facade()._MAX_RUN_INPUT_BYTES:
        return {"ok": False, "error": "input_data 过大"}
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = _facade().list_employees_exec()
        employee_index = {
            _facade().norm_pkg_id(r.get("id")): r
            for r in rows
            if _facade().norm_pkg_id(r.get("id"))
        }
        if _facade().norm_pkg_id(target) not in employee_index:
            return {"ok": False, "error": "目标员工未部署（执行库未注册）"}
        provider_map = _facade()._build_provider_status_map(session, int(created_by_user_id))
        fernet_ok = _facade().fernet_configured()
        manifest_cache: _facade().Dict[
            str, _facade().Optional[_facade().Dict[str, _facade().Any]]
        ] = {}
        deps_map: _facade().Dict[str, _facade().List[str]] = {}
        missing_dep_map: _facade().Dict[str, _facade().List[str]] = {}

        def _deps_for(eid: str) -> _facade().List[str]:
            if eid in deps_map:
                return deps_map[eid]
            manifest = _facade()._load_manifest_for_employee(
                session, eid, employee_index, manifest_cache
            )
            if not isinstance(manifest, dict):
                deps_map[eid] = []
                return deps_map[eid]
            deps_map[eid] = _facade()._extract_manifest_dependencies(manifest)
            return deps_map[eid]

        selected: _facade().Set[str] = {target}
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
        order, cycle_nodes = _facade()._topo_sort(selected, deps_map)
        if cycle_nodes:
            _facade().logger.warning(
                "duty graph cycle detected: %s order=%s", ", ".join(cycle_nodes), order
            )
            return {
                "ok": False,
                "error": "员工依赖图存在循环: " + " -> ".join(cycle_nodes),
            }
        run = _facade().DutyGraphRun(
            created_by_user_id=int(created_by_user_id),
            target_employee_id=target,
            task=task_s,
            input_data_json=_facade()._json_dumps(raw_input),
            include_dependencies=include_dependencies,
            max_concurrency=max_concurrency,
            allow_high_risk_real_run=allow_high_risk_real_run,
            status="running",
            total_nodes=len(order),
            started_at=_facade().datetime.now(_facade().timezone.utc),
        )
        session.add(run)
        session.flush()
        run_id = int(run.id)
        for idx, eid in enumerate(order):
            session.add(
                _facade().DutyGraphRunNode(
                    run_id=run_id,
                    employee_id=eid,
                    order_index=idx,
                    depends_on_json=_facade()._json_dumps(
                        sorted((d for d in _deps_for(eid) if d in selected))
                    ),
                    status="pending",
                )
            )
        session.commit()
        node_status: _facade().Dict[str, str] = {}
        first_error = ""
        runtime = _facade().get_default_employee_client()
        layer_index: _facade().Dict[str, int] = {}
        for eid in order:
            d = (
                _facade()._json_loads(_facade()._json_dumps(deps_map.get(eid, [])), [])
                if False
                else deps_map.get(eid, [])
            )
            relevant = [x for x in d or [] if x in selected]
            layer_index[eid] = (
                max((layer_index.get(x, -1) for x in relevant), default=-1) + 1 if relevant else 0
            )
        layers: _facade().Dict[int, _facade().List[str]] = {}
        for eid, lvl in layer_index.items():
            layers.setdefault(lvl, []).append(eid)
        from concurrent.futures import ThreadPoolExecutor
        from threading import Lock

        status_lock = Lock()
        error_lock = Lock()

        def _execute_one(eid: str) -> None:
            nonlocal first_error
            sf2 = _facade().get_session_factory()
            with sf2() as sess2:
                node = (
                    sess2.query(_facade().DutyGraphRunNode)
                    .filter(
                        _facade().DutyGraphRunNode.run_id == run_id,
                        _facade().DutyGraphRunNode.employee_id == eid,
                    )
                    .first()
                )
                if not node:
                    return
                deps_local = _facade()._json_loads(node.depends_on_json or "[]", [])
                with status_lock:
                    blocked = [d for d in deps_local if node_status.get(d) not in ("success",)]
                if blocked:
                    node.status = "skipped"
                    node.error = f"上游未成功：{', '.join(blocked)}"
                    node.completed_at = _facade().datetime.now(_facade().timezone.utc)
                    sess2.commit()
                    with status_lock:
                        node_status[eid] = "skipped"
                    return
                missing = missing_dep_map.get(eid) or []
                if missing:
                    node.status = "skipped"
                    node.error = f"缺少依赖员工：{', '.join(missing)}"
                    node.completed_at = _facade().datetime.now(_facade().timezone.utc)
                    sess2.commit()
                    with status_lock:
                        node_status[eid] = "skipped"
                    return
                cap = _facade()._analyze_employee_capability(
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
                        "；".join((_facade()._as_str(r) for r in reasons if _facade()._as_str(r)))
                        or "员工当前不可执行"
                    )
                    node.summary = "capability blocked"
                    node.completed_at = _facade().datetime.now(_facade().timezone.utc)
                    node.result_json = _facade()._json_dumps({"capability": cap}, max_chars=3000)
                    sess2.commit()
                    with status_lock:
                        node_status[eid] = "skipped"
                    return
                if bool(cap.get("risk", {}).get("high_risk")) and (not allow_high_risk_real_run):
                    node.status = "skipped"
                    node.error = "高风险动作未确认（allow_high_risk_real_run=false）"
                    node.summary = "confirmation required"
                    node.completed_at = _facade().datetime.now(_facade().timezone.utc)
                    node.result_json = _facade()._json_dumps({"capability": cap}, max_chars=3000)
                    sess2.commit()
                    with status_lock:
                        node_status[eid] = "skipped"
                    return
                node.status = "running"
                node.started_at = _facade().datetime.now(_facade().timezone.utc)
                sess2.commit()
            t0 = _facade().time.perf_counter()
            result: _facade().Dict[str, _facade().Any] = {}
            error_text = ""
            status = "success"
            llm_tokens = 0
            duration_ms = 0.0
            exec_kw: _facade().Dict[str, _facade().Any] = {}
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
                    duration_ms = round((_facade().time.perf_counter() - t0) * 1000, 3)
            except RECOVERABLE_ERRORS as exc:
                status = "failed"
                error_text = str(exc)
                duration_ms = round((_facade().time.perf_counter() - t0) * 1000, 3)
                result = {"error": error_text}
            sf3 = _facade().get_session_factory()
            with sf3() as sess3:
                node = (
                    sess3.query(_facade().DutyGraphRunNode)
                    .filter(
                        _facade().DutyGraphRunNode.run_id == run_id,
                        _facade().DutyGraphRunNode.employee_id == eid,
                    )
                    .first()
                )
                if not node:
                    return
                metric = (
                    sess3.query(_facade().EmployeeExecutionMetric)
                    .filter(
                        _facade().EmployeeExecutionMetric.employee_id == eid,
                        _facade().EmployeeExecutionMetric.user_id == int(created_by_user_id),
                    )
                    .order_by(_facade().EmployeeExecutionMetric.id.desc())
                    .first()
                )
                node.metric_id = int(metric.id) if metric else None
                node.status = status
                node.completed_at = _facade().datetime.now(_facade().timezone.utc)
                node.duration_ms = duration_ms
                node.llm_tokens = llm_tokens
                node.error = error_text[:2000]
                node.summary = (
                    _facade()._as_str(result.get("result", ""))[:1000]
                    if isinstance(result, dict)
                    else ""
                )
                node.result_json = _facade()._json_dumps(
                    result, max_chars=_facade()._MAX_RESULT_BYTES
                )
                sess3.commit()
            with status_lock:
                node_status[eid] = status
            if status == "failed":
                with error_lock:
                    if not first_error:
                        first_error = error_text[:1000] or f"{eid} 执行失败"

        session.commit()
        for lvl in sorted(layers.keys()):
            layer_eids = layers[lvl]
            if max_concurrency <= 1 or len(layer_eids) == 1:
                for eid in layer_eids:
                    _execute_one(eid)
            else:
                with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
                    list(pool.map(_execute_one, layer_eids))
        run_row = session.get(_facade().DutyGraphRun, run_id)
        if not run_row:
            return {"ok": False, "error": "运行记录丢失"}
        rows2 = (
            session.query(_facade().DutyGraphRunNode)
            .filter(_facade().DutyGraphRunNode.run_id == run_id)
            .all()
        )
        success_count = len([r for r in rows2 if r.status == "success"])
        failed_count = len([r for r in rows2 if r.status == "failed"])
        skipped_count = len([r for r in rows2 if r.status == "skipped"])
        run_row.success_count = success_count
        run_row.failed_count = failed_count
        run_row.skipped_count = skipped_count
        run_row.status = "failed" if failed_count > 0 else "completed"
        run_row.error = first_error
        run_row.completed_at = _facade().datetime.now(_facade().timezone.utc)
        session.commit()
        out = _facade()._serialize_run(session, run_id)
        out["ok"] = True
        return out


@_facade().router.post("/duty-graph/runs")
def create_duty_graph_run(
    body: _facade().Dict[str, _facade().Any] = _facade().Body(default_factory=dict),
    admin_user: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    target = _facade()._as_str(body.get("target_employee_id"))
    task = _facade()._as_str(body.get("task"))
    include_dependencies = bool(body.get("include_dependencies", True))
    allow_high_risk_real_run = bool(body.get("allow_high_risk_real_run", False))
    if not target:
        raise _facade().HTTPException(400, "target_employee_id 不能为空")
    if not task:
        raise _facade().HTTPException(400, "task 不能为空")
    try:
        max_concurrency = int(body.get("max_concurrency", 2))
    except (TypeError, ValueError):
        max_concurrency = 2
    raw_input = body.get("input_data", {})
    if raw_input is None:
        raw_input = {}
    if not isinstance(raw_input, dict):
        raise _facade().HTTPException(400, "input_data 必须是对象")
    if len(_facade()._json_dumps(raw_input)) > _facade()._MAX_RUN_INPUT_BYTES:
        raise _facade().HTTPException(400, "input_data 过大")
    out = _facade().execute_duty_graph_programmatic(
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
        msg = _facade()._as_str(out.get("error")) or "duty graph failed"
        code = 404 if "不存在" in msg else 400
        raise _facade().HTTPException(code, msg)
    out.pop("ok", None)
    return out


@_facade().router.get("/duty-graph/runs/{run_id}")
def get_duty_graph_run(
    run_id: int, admin_user: _facade().User = _facade().Depends(_facade().require_admin)
) -> _facade().Dict[str, _facade().Any]:
    _ = admin_user
    if run_id <= 0:
        raise _facade().HTTPException(400, "run_id 非法")
    sf = _facade().get_session_factory()
    with sf() as session:
        return _facade()._serialize_run(session, run_id)


@_facade().router.get("/duty-graph/health")
def duty_graph_health(
    admin_user: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    """全员自治闭环健康看板：缺岗、调度器、待审 CR、未识别事件等。"""
    _ = admin_user
    out: _facade().Dict[str, _facade().Any] = {"ok": True}
    try:
        from modstore_server.duty_roster import YUANGON_AREAS, all_planned_employee_ids
        from modstore_server.models import CatalogItem

        sf = _facade().get_session_factory()
        with sf() as session:
            registered = {
                _facade().norm_pkg_id(r[0])
                for r in session.query(CatalogItem.pkg_id)
                .filter(CatalogItem.artifact == "employee_pack")
                .all()
                if r[0]
            }
        planned = set(all_planned_employee_ids())
        missing_local: _facade().List[str] = []
        for pid in planned:
            if not _facade().resolve_employee_pack_dir(pid):
                missing_local.append(pid)
        out["staffing"] = {
            "planned_count": len(planned),
            "registered_count": len(planned & registered),
            "missing_employees": sorted(planned - registered),
            "missing_local_employee_packs": sorted(missing_local),
            "extra_employees": sorted(registered - planned),
            "areas": [
                {
                    "key": k,
                    "label": v.get("label", k),
                    "missing": sorted(set(v.get("ids") or []) - registered),
                }
                for (k, v) in YUANGON_AREAS.items()
            ],
        }
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("staffing summary failed")
        out["staffing"] = {"error": str(exc)}
    try:
        from modstore_server.workflow_scheduler import list_employee_cron_jobs

        out["employee_cron_jobs"] = list_employee_cron_jobs()
    except RECOVERABLE_ERRORS as exc:
        out["employee_cron_jobs"] = []
        out["employee_cron_jobs_error"] = str(exc)
    try:
        from modstore_server.models import EmployeeChangeRequest

        sf = _facade().get_session_factory()
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
    except RECOVERABLE_ERRORS as exc:
        out["change_requests"] = {"error": str(exc)}
    try:
        from datetime import timedelta

        from modstore_server.models import IncidentEvent

        sf = _facade().get_session_factory()
        cutoff = _facade().datetime.now(_facade().timezone.utc) - timedelta(hours=24)
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
    except RECOVERABLE_ERRORS as exc:
        out["incident_unknown_24h"] = 0
        out["incident_unknown_error"] = str(exc)
    try:
        out["env_flags"] = {
            "MODSTORE_DAILY_ORCHESTRATOR_ENABLED": _facade().os.environ.get(
                "MODSTORE_DAILY_ORCHESTRATOR_ENABLED", "0"
            ),
            "MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED": _facade().os.environ.get(
                "MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED", "1"
            ),
            "MODSTORE_AUTO_APPROVE_ENABLED": _facade().os.environ.get(
                "MODSTORE_AUTO_APPROVE_ENABLED", "0"
            ),
            "MODSTORE_CR_GIT_BRANCH_ENABLED": _facade().os.environ.get(
                "MODSTORE_CR_GIT_BRANCH_ENABLED", "1"
            ),
        }
    except RECOVERABLE_ERRORS:
        pass
    return out
