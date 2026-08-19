# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.all_hands_report")


def _should_standby_manifest_report(pkg_id: str, *, user_question: str) -> bool:
    """制作车间 + 无用户提问 → 跳过 execute_employee_task，避免流水线 JSON 告警。"""
    return not (user_question or "").strip() and pkg_id in _facade().CRAFT_WORKSHOP_STANDBY_IDS


def _craft_pipeline_standby_context(
    pkg_id: str, signals: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    """给待机汇报补充流水线语境，避免 LLM 误判为缺上游故障。"""
    deps = signals.get("depends_on") if isinstance(signals.get("depends_on"), list) else []
    upstream = [str(d).strip() for d in deps if str(d).strip()]
    downstream_hint: _facade().Dict[str, _facade().List[str]] = {
        "intent-analyst": ["employee-planner", "artifact-generator"],
        "employee-planner": ["artifact-generator", "quality-validator"],
        "artifact-generator": ["quality-validator", "miniapp-builder"],
        "workflow-automator": ["pack-registrar"],
        "pack-registrar": ["sandbox-tester"],
        "sandbox-tester": ["code-validator", "self-checker"],
    }
    return {
        "mode": "all_hands_standby",
        "pipeline_area": "craft-workshop",
        "instruction": "员工大会待机汇报：不要执行流水线步骤，不要输出 JSON 告警。说明本岗在制作车间 13 步流水线中的位置、depends_on 与就绪条件即可。",
        "upstream_employees": upstream,
        "typical_downstream": downstream_hint.get(pkg_id, []),
        "synthetic_upstream_note": "当前无真实上游产物属预期；用 manifest 描述待机职责，勿写「输入不足」。",
    }


def _is_standby_pipeline_json_noise(text: str) -> bool:
    t = (text or "").strip()
    if not t.startswith("{"):
        return False
    if "输入不足" not in t and '"warnings"' not in t:
        return False
    try:
        obj = _facade().json.loads(t)
    except _facade().json.JSONDecodeError:
        return "输入不足" in t and "warnings" in t.lower()
    if not isinstance(obj, dict):
        return False
    warns = obj.get("warnings")
    return isinstance(warns, list) and any(("输入不足" in str(w) for w in warns))


def _coerce_standby_excerpt(text: str, row: _facade().Dict[str, _facade().Any]) -> str:
    """把待机误输出的流水线 JSON 告警压成可读一句，避免污染会议摘要。"""
    if not _facade()._is_standby_pipeline_json_noise(text):
        return text
    eid = str(row.get("employee_id") or "").strip()
    name = str(row.get("name") or eid).strip()
    area = str(row.get("area") or "制作车间").strip() or "制作车间"
    summ = ""
    try:
        obj = _facade().json.loads(text.strip())
        if isinstance(obj, dict):
            summ = str(obj.get("summary") or "").strip()
    except _facade().json.JSONDecodeError:
        pass
    if summ and (not summ.startswith("{")) and ("输入不足" not in summ[:80]):
        return summ
    return f"【{name}】（{eid}）在 {area} 流水线中处于**待机**：职责与 manifest 已就绪，等待上游工单/产物输入；本次大会未执行流水线步骤，无异常。"


def _resolve_employee_pairs(
    requested_ids: _facade().Optional[_facade().List[str]], *, max_employees: int
) -> _facade().List[_facade().Tuple[str, str]]:
    """返回 ``[(pkg_id, display_name), ...]``。

    **编制员工**（``duty_roster.all_planned_employee_ids``）与公开市场无关：不要求
    ``catalog_items.is_public``，也不要求已做「市场上架」。只要能加载员工包即可：

    - Postgres ``catalog_items`` 中 ``artifact=employee_pack``；**或**
    - XC 本地 ``catalog_store.packages.json`` 中已登记 ``artifact=employee_pack`` 且
      ``files/`` 下有对应 zip（与 :func:`modstore_server.employee_runtime.load_employee_pack` 一致）。
    """
    roster = _facade().all_planned_employee_ids()
    from modstore_server.catalog_store import employee_pack_records_from_store

    xc = employee_pack_records_from_store()
    sf = _facade().get_session_factory()
    with sf() as session:
        rows = (
            session.query(_facade().CatalogItem.pkg_id, _facade().CatalogItem.name)
            .filter(_facade().CatalogItem.artifact == "employee_pack")
            .all()
        )
    db_ids = {str(r[0]) for r in rows}
    name_by_id = {str(r[0]): str(r[1] or r[0]) for r in rows}
    for pid, rec in xc.items():
        if pid not in name_by_id:
            name_by_id[pid] = str(rec.get("name") or pid).strip() or pid
    xc_ids = set(xc.keys())
    available = db_ids | xc_ids
    if requested_ids:
        pairs: _facade().List[_facade().Tuple[str, str]] = []
        for pid in requested_ids:
            pid = str(pid or "").strip()
            if not pid or pid not in available:
                continue
            pairs.append((pid, name_by_id.get(pid, pid)))
    else:
        pairs = sorted(
            ((pid, name_by_id.get(pid, pid)) for pid in roster if pid in available),
            key=lambda x: x[0],
        )
    return pairs[: _facade().clamp_all_hands_max_employees(max_employees)]


def _recent_failures(
    employee_id: str, limit: int = 6
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """读员工最近真实失败/告警的执行流水，给"问题与解决"段落做事实根基。

    只纳入真正的失败状态（``failed``、``error``，以及有非空 error 字段的 ``success``）；
    排除 ``skipped``、``blocked_by_risk_gate``、``warning`` 等正常/预期状态。
    默认只取最近 72h 内的记录（可通过 ``MODSTORE_RECENT_FAILURES_HOURS`` 覆盖）。
    同一 ``(task 前缀, error 前缀)`` 组合去重，避免重复 craft 步骤生成多张 P0 卡。
    """
    import os

    hours = int(os.environ.get("MODSTORE_RECENT_FAILURES_HOURS") or 72)
    sf = _facade().get_session_factory()
    out: _facade().List[_facade().Dict[str, _facade().Any]] = []
    seen_keys: set = set()
    with sf() as session:
        cutoff: _facade().Optional[_facade().datetime] = None
        if hours > 0:
            from datetime import timedelta

            cutoff = _facade().datetime.now(_facade().timezone.utc).replace(
                tzinfo=None
            ) - timedelta(hours=hours)
        q = session.query(_facade().EmployeeExecutionMetric).filter(
            _facade().EmployeeExecutionMetric.employee_id == employee_id
        )
        if cutoff is not None:
            q = q.filter(_facade().EmployeeExecutionMetric.created_at >= cutoff)
        rows = q.order_by(_facade().desc(_facade().EmployeeExecutionMetric.id)).limit(120).all()
        for r in rows:
            status = str(getattr(r, "status", "") or "")
            err = (getattr(r, "error", "") or "").strip()
            is_real_failure = status in ("failed", "error")
            is_success_with_err = status == "success" and bool(err)
            if not (is_real_failure or is_success_with_err):
                continue
            task_key = str(r.task or "")[:60]
            err_key = err[:80]
            dedup = (task_key, err_key)
            if dedup in seen_keys:
                continue
            seen_keys.add(dedup)
            out.append(
                {
                    "id": int(r.id),
                    "task": str(r.task or "")[:160],
                    "status": status,
                    "duration_ms": float(r.duration_ms or 0.0),
                    "llm_tokens": int(r.llm_tokens or 0),
                    "error": err[:600],
                    "created_at": (
                        r.created_at.replace(tzinfo=_facade().timezone.utc).isoformat()
                        if isinstance(r.created_at, _facade().datetime)
                        and r.created_at.tzinfo is None
                        else r.created_at.isoformat() if r.created_at else None
                    ),
                }
            )
            if len(out) >= limit:
                break
    return out


def _load_yuangon_employee_meta(pkg_id: str) -> _facade().Dict[str, _facade().Any]:
    """读取 yuangon/<area>/<pkg_id>/employee.yaml 中的 owner/area/domain 等元数据。"""
    from modstore_server.daily_employee_briefs import _resolve_pack_dir

    area = _facade().yuangon_area_for_pkg(pkg_id) or ""
    if not area:
        return {}
    (_root, pack_dir) = _resolve_pack_dir(area, pkg_id)
    yaml_path = pack_dir / "employee.yaml"
    if not yaml_path.is_file():
        return {"area": area}
    try:
        import yaml

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _facade().logger.debug("all_hands: employee.yaml read failed pkg_id=%s err=%s", pkg_id, exc)
        return {"area": area}
    if not isinstance(data, dict):
        return {"area": area}
    meta: _facade().Dict[str, _facade().Any] = {"area": str(data.get("area") or area).strip()}
    for key in ("owner", "domain", "id", "name", "version"):
        val = data.get(key)
        if val is not None and str(val).strip():
            meta[key] = str(val).strip()
    sla = data.get("sla")
    if isinstance(sla, dict):
        meta["sla"] = sla
    trig = data.get("triggers")
    if isinstance(trig, dict):
        meta["triggers"] = trig
    deps = data.get("depends_on")
    if isinstance(deps, list):
        meta["depends_on_yaml"] = [str(x).strip() for x in deps if str(x).strip()][:8]
    bc = data.get("business_context")
    if isinstance(bc, dict) and bc:
        meta["business_context"] = bc
    ci_paths = data.get("ci_coverage_artifacts")
    if isinstance(ci_paths, list) and ci_paths:
        meta["ci_coverage_artifacts"] = [str(x).strip() for x in ci_paths if str(x).strip()][:12]
    return meta


def _snapshot_pending_change_requests(
    limit: int = 12,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    from modstore_server.models import EmployeeChangeRequest, get_session_factory

    out: _facade().List[_facade().Dict[str, _facade().Any]] = []
    try:
        sf = get_session_factory()
        with sf() as session:
            rows = (
                session.query(EmployeeChangeRequest)
                .filter(EmployeeChangeRequest.status == "pending")
                .order_by(_facade().desc(EmployeeChangeRequest.id))
                .limit(max(1, min(limit, 30)))
                .all()
            )
            for r in rows:
                out.append(
                    {
                        "id": int(r.id),
                        "source_employee_id": str(r.source_employee_id or ""),
                        "change_kind": str(r.change_kind or ""),
                        "risk_level": str(r.risk_level or ""),
                        "status": str(r.status or ""),
                        "diff_summary": str(r.diff_summary or "")[:400],
                        "target_paths": (
                            _facade().json.loads(r.target_paths_json or "[]")[:6]
                            if str(r.target_paths_json or "").strip().startswith("[")
                            else []
                        ),
                        "git_branch": str(r.git_branch or "")[:120],
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                )
    except Exception as exc:
        _facade().logger.debug("all_hands: pending change requests snapshot failed: %s", exc)
    return out


def _snapshot_employee_cron_overview(
    limit: int = 24,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    try:
        from modstore_server.workflow_scheduler import list_employee_cron_jobs

        jobs = list_employee_cron_jobs() or []
    except Exception as exc:
        _facade().logger.debug("all_hands: cron overview failed: %s", exc)
        return []
    out: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for row in jobs[: max(1, min(limit, 40))]:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "employee_id": str(row.get("employee_id") or row.get("id") or ""),
                "next_run_time": str(row.get("next_run_time") or ""),
                "trigger": str(row.get("trigger") or "")[:120],
            }
        )
    return out


def _all_hands_role_context(pkg_id: str) -> _facade().Dict[str, _facade().Any]:
    """按岗位注入员工大会专用上下文，避免「缺 Change ID / 缺调度清单」类空答。"""
    ctx: _facade().Dict[str, _facade().Any] = {"mode": "all_hands_meeting"}
    if pkg_id == "change-request-auditor":
        pending = _facade()._snapshot_pending_change_requests()
        ctx["pending_change_requests"] = pending
        ctx["instruction"] = (
            "若 pending_change_requests 非空：逐条引用 id / source_employee_id / diff_summary 说明评审要点；若为空：说明当前无待审变更，并列出 manifest 中的评审流程与 depends_on。"
        )
    elif pkg_id == "daily-orchestrator":
        ctx["employee_cron_overview"] = _facade()._snapshot_employee_cron_overview()
        ctx["instruction"] = (
            "结合 employee_cron_overview 说明当前定时任务覆盖与缺口；无记录时依据 manifest 描述编排职责。"
        )
    elif pkg_id in {"dbops-engineer", "log-monitor-incident", "retention-officer"}:
        ctx["instruction"] = (
            "员工大会为汇总模式，无实时 DB/日志事件流；请基于 manifest、recent_failures 与 yuangon 节选说明职责边界与待命方式。"
        )
    elif pkg_id == "code-validator":
        ctx["instruction"] = (
            "校验 employee.yaml 时 owner/area 须为字符串；manifest.employee_config_v2 须含 actions.handlers。汇报中引用 manifest_signals 与 yuangon employee.yaml 字段，不要臆造 schema。"
        )
    elif pkg_id == "employee-pack-quality-interviewer":
        ctx["instruction"] = (
            "质询时检查 behavior_rules 是否过 long/重复、skills.brief 是否截断、employee_config_v2 结构是否完整（identity/cognition/actions/collaboration）。"
        )
    elif pkg_id in _facade().CRAFT_WORKSHOP_STANDBY_IDS:
        ctx["mode"] = "all_hands_standby"
        ctx["pipeline_area"] = "craft-workshop"
        ctx["instruction"] = (
            "员工大会待机汇报：不要执行流水线步骤，不要输出 JSON 或「输入不足」告警；说明本岗在制作车间流水线中的职责与就绪条件即可。"
        )
    return ctx


def _manifest_signals(pkg_id: str) -> _facade().Dict[str, _facade().Any]:
    """从员工包 manifest 抽取汇报 grounding 字段（identity/role/handlers/depends_on/behavior_rules）。"""
    out: _facade().Dict[str, _facade().Any] = {
        "name": pkg_id,
        "description": "",
        "persona": "",
        "expertise": [],
        "handlers": [],
        "depends_on": [],
        "skills": [],
        "behavior_rules": [],
        "workflow_id": 0,
        "owner": "",
        "area": "",
        "domain": "",
        "employee_config_v2_outline": {},
    }
    yuangon_meta = _facade()._load_yuangon_employee_meta(pkg_id)
    out["owner"] = str(yuangon_meta.get("owner") or "")
    out["area"] = str(yuangon_meta.get("area") or _facade().yuangon_area_for_pkg(pkg_id) or "")
    out["domain"] = str(yuangon_meta.get("domain") or "")
    try:
        sf = _facade().get_session_factory()
        with sf() as session:
            pack = _facade().load_employee_pack(session, pkg_id)
        man = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
        v2 = man.get("employee_config_v2") if isinstance(man, dict) else {}
        ident = v2.get("identity") or {}
        cog = v2.get("cognition") or {}
        agent = cog.get("agent") or {}
        role = agent.get("role") or {}
        actions = v2.get("actions") or {}
        collab = v2.get("collaboration") or {}
        wf = collab.get("workflow") or {}
        out["name"] = str(ident.get("name") or man.get("name") or pkg_id)
        out["description"] = str(ident.get("description") or man.get("description") or "")[:280]
        out["persona"] = str(role.get("persona") or agent.get("system_prompt") or "")[:400]
        sp = str(agent.get("system_prompt") or "").strip()
        out["system_prompt_present"] = bool(sp)
        out["system_prompt_chars"] = len(sp)
        if sp and (not out["persona"]):
            out["persona"] = sp[:400]
        if isinstance(role.get("expertise"), list):
            out["expertise"] = [str(x) for x in role["expertise"] if str(x).strip()][:8]
        if isinstance(actions.get("handlers"), list):
            out["handlers"] = [str(x) for x in actions["handlers"] if str(x).strip()][:12]
        if isinstance(cog.get("skills"), list):
            for s in cog["skills"][:6]:
                if isinstance(s, dict) and s.get("name"):
                    out["skills"].append(
                        {
                            "name": str(s.get("name"))[:48],
                            "brief": str(s.get("brief") or s.get("description") or "")[:160],
                            "kind": str(s.get("kind") or "")[:32],
                        }
                    )
        if isinstance(agent.get("behavior_rules"), list):
            for rule in agent["behavior_rules"]:
                if len(out["behavior_rules"]) >= 8:
                    break
                text = ""
                if isinstance(rule, str):
                    text = rule.strip()
                elif isinstance(rule, dict):
                    name = str(rule.get("name") or rule.get("rule_id") or "").strip()
                    desc = str(rule.get("description") or rule.get("text") or "").strip()
                    if name and desc:
                        text = f"{name}: {desc}"
                    else:
                        text = name or desc
                if text:
                    if len(text) > 120:
                        text = text[:117].rstrip() + "…"
                    out["behavior_rules"].append(text)
        deps_raw = collab.get("depends_on")
        if not isinstance(deps_raw, list):
            deps_raw = man.get("depends_on") if isinstance(man, dict) else None
        if isinstance(deps_raw, list):
            out["depends_on"] = [str(x) for x in deps_raw if str(x).strip()][:8]
        wp = v2.get("workspace_policy") if isinstance(v2.get("workspace_policy"), dict) else {}
        scope_globs = wp.get("scope_globs") if isinstance(wp.get("scope_globs"), list) else []
        forbidden_globs = (
            wp.get("forbidden_globs") if isinstance(wp.get("forbidden_globs"), list) else []
        )
        ident_block = v2.get("identity") if isinstance(v2.get("identity"), dict) else {}
        if not out["owner"] and ident_block.get("owner"):
            out["owner"] = str(ident_block.get("owner") or "").strip()
        if not out["area"] and ident_block.get("area"):
            out["area"] = str(ident_block.get("area") or "").strip()
        out["employee_config_v2_outline"] = {
            "identity_id": str(ident_block.get("id") or pkg_id),
            "artifact": str(ident_block.get("artifact") or "employee_pack"),
            "handlers": list(out["handlers"]),
            "depends_on": list(out["depends_on"]),
            "workspace_scope_globs": [str(x) for x in scope_globs if str(x).strip()][:6],
            "workspace_forbidden_globs": [str(x) for x in forbidden_globs if str(x).strip()][:4],
            "skills_count": len(out["skills"]),
            "behavior_rules_count": len(out["behavior_rules"]),
        }
        try:
            out["workflow_id"] = int(wf.get("workflow_id") or 0)
        except (TypeError, ValueError):
            out["workflow_id"] = 0
        sig_block = (
            v2.get("manifest_signals") if isinstance(v2.get("manifest_signals"), dict) else {}
        )
        ci_art = sig_block.get("ci_coverage_artifacts")
        if isinstance(ci_art, list) and ci_art:
            out["ci_coverage_artifacts"] = [str(x).strip() for x in ci_art if str(x).strip()][:12]
    except Exception as exc:
        _facade().logger.debug("all_hands: manifest read failed pkg_id=%s err=%s", pkg_id, exc)
    if "ci_coverage_artifacts" not in out:
        yg_ci = yuangon_meta.get("ci_coverage_artifacts")
        if isinstance(yg_ci, list) and yg_ci:
            out["ci_coverage_artifacts"] = [str(x).strip() for x in yg_ci if str(x).strip()][:12]
    bc = yuangon_meta.get("business_context")
    if isinstance(bc, dict) and bc:
        out["business_context"] = bc
    return out


async def _standby_manifest_report_via_bench(
    *,
    pkg_id: str,
    display_name: str,
    task_text: str,
    inp: _facade().Dict[str, _facade().Any],
    user_id: int,
    bench_provider: str,
    bench_model: str,
) -> _facade().Tuple[str, str, int]:
    """制作车间待机：用大会任务模板 + bench LLM，不经员工 cognition（避免 JSON 告警）。"""
    payload = dict(inp)
    if pkg_id in _facade().CRAFT_WORKSHOP_STANDBY_IDS:
        sig = payload.get("manifest_signals")
        if isinstance(sig, dict):
            payload["craft_workshop_standby"] = _facade()._craft_pipeline_standby_context(
                pkg_id, sig
            )
    user_content = f"{task_text}\n\n---\n\n以下为结构化输入（JSON），请据此撰写四段 Markdown 汇报：\n{_facade().json.dumps(payload, ensure_ascii=False)[:14000]}"
    messages = [
        {"role": "system", "content": _facade()._ALL_HANDS_STANDBY_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    try:
        from modstore_server.services.llm import chat_dispatch_via_session

        sf = _facade().get_session_factory()
        with sf() as db:
            result = await chat_dispatch_via_session(
                db, int(user_id or 0), bench_provider, bench_model, messages, max_tokens=4096
            )
    except Exception as exc:
        return ("", f"待机汇报 LLM 异常：{exc}"[:800], 0)
    if not isinstance(result, dict) or not result.get("ok"):
        err = str((result or {}).get("error") or "bench LLM 未返回有效内容").strip()
        return ("", err[:800], 0)
    md = str(result.get("content") or "").strip()
    if not md:
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            msg0 = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg0, dict):
                md = str(msg0.get("content") or "").strip()
    tokens = 0
    raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
    usage = raw.get("usage") if isinstance(raw, dict) else {}
    if isinstance(usage, dict):
        tokens = int(usage.get("total_tokens") or 0)
        if not tokens:
            tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
    return (md, "", tokens)


async def _report_one_employee(
    *,
    pkg_id: str,
    display_name: str,
    other_employees: _facade().List[str],
    user_id: int,
    bench_provider: str,
    bench_model: str,
    with_research: bool,
    user_question: _facade().Optional[str] = None,
) -> _facade().Dict[str, _facade().Any]:
    started_at = _facade().datetime.now(_facade().timezone.utc).isoformat()
    warns: _facade().List[str] = []
    research_pack = ""
    research_sources: _facade().List[_facade().Dict[str, str]] = []
    if with_research:
        seed = _facade().resolve_daily_brief_research_brief(pkg_id, display_name)
        try:
            rc = await _facade().build_research_context(
                brief=seed,
                intent="employee",
                max_repos=2,
                max_chars=5000,
                max_web=6,
                user_id=user_id,
                rate_limit_bucket="agent_tool",
            )
            if rc.get("ok"):
                research_pack = str(rc.get("context_pack") or "")
                research_sources = [
                    {"title": str(s.get("title") or ""), "url": str(s.get("url") or "")}
                    for s in rc.get("sources") or []
                    if isinstance(s, dict)
                ][:8]
            else:
                warns.append(str(rc.get("error") or "research failed"))
            for w in rc.get("warnings") or []:
                warns.append(str(w))
        except Exception as exc:
            _facade().logger.warning("all_hands research failed pkg_id=%s err=%s", pkg_id, exc)
            warns.append(f"research 失败：{exc}")
    (excerpt, yg_warns) = _facade().collect_yuangon_pack_excerpt(pkg_id)
    warns.extend(yg_warns)
    failures = _facade()._recent_failures(pkg_id)
    yuangon_meta = _facade()._load_yuangon_employee_meta(pkg_id)
    signals = _facade()._manifest_signals(pkg_id)
    user_q = (user_question or "").strip()
    if user_q:
        task_text = _facade().ALL_HANDS_QA_TASK_TEMPLATE.format(
            employee_id=pkg_id, user_question=user_q
        )
    else:
        task_text = _facade().ALL_HANDS_TASK_TEMPLATE.format(employee_id=pkg_id)
    inp: _facade().Dict[str, _facade().Any] = {
        "research_context": research_pack,
        "research_sources": research_sources,
        "yuangon_pack_excerpt": excerpt,
        "recent_failures": failures,
        "context_availability": {
            "yuangon_excerpt": bool(excerpt.strip()),
            "research_pack": bool(research_pack.strip()),
            "execution_failures": bool(failures),
        },
        "employee_id": pkg_id,
        "employee_label": display_name,
        "manifest_signals": signals,
        "other_employees": other_employees,
        "yuangon_area": _facade().yuangon_area_for_pkg(pkg_id) or "",
        "yuangon_employee_meta": yuangon_meta,
        "role_context": _facade()._all_hands_role_context(pkg_id),
        "user_question": user_q,
        "all_hands_standby": not bool(user_q),
        "allow_high_risk_real_run": True,
    }
    _hr_gate = (_facade().os.environ.get("MODSTORE_RISK_HIGH_GATE_TOKEN") or "").strip()
    if _hr_gate:
        inp["high_risk_gate_token"] = _hr_gate
    use_standby_bench = _facade()._should_standby_manifest_report(pkg_id, user_question=user_q)
    llm_tokens = 0
    duration_ms = 0.0
    if use_standby_bench:
        (text, cog_err, llm_tokens) = await _facade()._standby_manifest_report_via_bench(
            pkg_id=pkg_id,
            display_name=display_name,
            task_text=task_text,
            inp=inp,
            user_id=user_id,
            bench_provider=bench_provider,
            bench_model=bench_model,
        )
        if text:
            text = _facade()._coerce_standby_excerpt(
                text, {"employee_id": pkg_id, "name": display_name, "area": signals.get("area")}
            )
        completed = _facade().datetime.now(_facade().timezone.utc).isoformat()
        return {
            "employee_id": pkg_id,
            "name": display_name,
            "area": _facade().yuangon_area_for_pkg(pkg_id) or "",
            "status": "ok" if text else "model_error" if cog_err else "empty",
            "started_at": started_at,
            "completed_at": completed,
            "report_markdown": text,
            "cognition_error": cog_err[:800],
            "warnings": warns,
            "manifest_signals": signals,
            "recent_failures": failures,
            "research_sources": research_sources,
            "duration_ms": duration_ms,
            "llm_tokens": llm_tokens,
            "report_mode": "standby_manifest_bench",
        }

    def _run() -> _facade().Dict[str, _facade().Any]:
        return _facade().execute_employee_task(
            pkg_id, task_text, inp, user_id, bench_llm_override=(bench_provider, bench_model)
        )

    out: _facade().Dict[str, _facade().Any] = {}
    try:
        from modstore_server.employee_executor import _is_transient_llm_error

        for attempt in range(3):
            out = await _facade().asyncio.to_thread(_run)
            cog_err = str(out.get("cognition_error") or "").strip()
            cog_err_lower = cog_err.lower()
            if (
                attempt < 2
                and cog_err
                and (
                    "429" in cog_err_lower
                    or "rate limit" in cog_err_lower
                    or "too many requests" in cog_err_lower
                    or _is_transient_llm_error(cog_err)
                )
            ):
                await _facade().asyncio.sleep(2.5 * (attempt + 1))
                continue
            break
    except Exception as exc:
        _facade().logger.exception("all_hands employee execute failed pkg_id=%s", pkg_id)
        return {
            "employee_id": pkg_id,
            "name": display_name,
            "area": _facade().yuangon_area_for_pkg(pkg_id) or "",
            "status": "error",
            "started_at": started_at,
            "completed_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
            "report_markdown": "",
            "cognition_error": str(exc)[:800],
            "warnings": warns + [f"执行抛异常：{exc}"[:200]],
            "manifest_signals": signals,
            "recent_failures": failures,
            "research_sources": research_sources,
        }
    text = (out.get("reasoning_excerpt") or "").strip()
    if inp.get("all_hands_standby"):
        text = _facade()._coerce_standby_excerpt(
            text,
            {
                "employee_id": pkg_id,
                "name": display_name,
                "area": _facade().yuangon_area_for_pkg(pkg_id) or "",
            },
        )
    cog_err = (out.get("cognition_error") or "").strip()
    return {
        "employee_id": pkg_id,
        "name": display_name,
        "area": _facade().yuangon_area_for_pkg(pkg_id) or "",
        "status": "ok" if text else "model_error" if cog_err else "empty",
        "started_at": started_at,
        "completed_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        "report_markdown": text,
        "cognition_error": cog_err[:800],
        "warnings": warns,
        "manifest_signals": signals,
        "recent_failures": failures,
        "research_sources": research_sources,
        "duration_ms": float(out.get("duration_ms") or 0.0),
        "llm_tokens": int(out.get("llm_tokens") or 0),
    }
