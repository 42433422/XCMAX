# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.all_hands_report")


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
    except RECOVERABLE_ERRORS as exc:
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
                db,
                int(user_id or 0),
                bench_provider,
                bench_model,
                messages,
                max_tokens=4096,
            )
    except RECOVERABLE_ERRORS as exc:
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
        except RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("all_hands research failed pkg_id=%s err=%s", pkg_id, exc)
            warns.append(f"research 失败：{exc}")
    excerpt, yg_warns = _facade().collect_yuangon_pack_excerpt(pkg_id)
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
        text, cog_err, llm_tokens = await _facade()._standby_manifest_report_via_bench(
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
                text,
                {
                    "employee_id": pkg_id,
                    "name": display_name,
                    "area": signals.get("area"),
                },
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
            pkg_id,
            task_text,
            inp,
            user_id,
            bench_llm_override=(bench_provider, bench_model),
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
    except RECOVERABLE_ERRORS as exc:
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
