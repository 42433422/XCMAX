# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Persistence entry point for natural-language workflow graphs."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.workflow_nl_graph")


async def apply_nl_workflow_graph(
    db: _facade().Session,
    user: _facade().User,
    *,
    workflow_id: int,
    brief: str,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
    target_employee_pack_id: _facade().Optional[str] = None,
    target_employee_label: _facade().Optional[str] = None,
    status_hook: _facade().Optional[_facade().Callable[[str], _facade().Any]] = None,
    preset_eskill_nodes: _facade().Optional[
        _facade().List[_facade().Dict[str, _facade().Any]]
    ] = None,
) -> _facade().Dict[str, _facade().Any]:
    """
    为已存在且属于当前用户的工作流生成节点与边。
    成功: ok=True, nodes_created, edges_created, sandbox_ok, validation_errors, llm_warnings
    失败: ok=False, error=...

    preset_eskill_nodes: 可选，由 employee_skill_register 预先注册的真脚本 ESkill 列表，
        格式 [{eskill_id: int, name: str, output_var: str}, ...]。
        传入后会在 system prompt 追加约束让 LLM 串接这些节点，并在落库时强制补齐漏掉的节点。
    """
    wf = (
        db.query(_facade().Workflow)
        .filter(_facade().Workflow.id == workflow_id, _facade().Workflow.user_id == user.id)
        .first()
    )
    if not wf:
        return {"ok": False, "error": "工作流不存在或无权访问"}
    from modstore_server.mod_scaffold_runner import resolve_llm_provider_model

    prov, mdl, err = resolve_llm_provider_model(db, user, provider, model)
    if err:
        return {"ok": False, "error": err}
    employee_pack_id = str(target_employee_pack_id or "").strip()
    employee_label = str(target_employee_label or "").strip()
    employee_node_requirements = ""
    if employee_pack_id:
        label_hint = f"（显示名：{employee_label}）" if employee_label else ""
        employee_node_requirements = f'\n\n本次工作流属于新生成的可执行员工包，画布必须打通该员工包：\n- 必须包含至少一个 node_type="employee" 节点，config.employee_id 必须精确填写 {employee_pack_id!r}{label_hint}。\n- employee 节点表示真实可执行员工包入口；业务前后处理仍可用 eskill 节点表达。\n- 推荐链路：start -> 若干 eskill/condition -> employee -> 若干 eskill/condition -> end。\n'
    preset_nodes: _facade().List[_facade().Dict[str, _facade().Any]] = []
    preset_requirements = ""
    if preset_eskill_nodes:
        preset_nodes = [
            p
            for p in preset_eskill_nodes
            if isinstance(p, dict) and p.get("eskill_id") and p.get("name")
        ]
    if preset_nodes:
        lines = "\n".join(
            (
                f"  {i + 1}. skill_id={p['eskill_id']} name={p['name']!r} output_var={p.get('output_var', 'result')!r}"
                for (i, p) in enumerate(preset_nodes)
            )
        )
        preset_requirements = f'\n\n【重要约束】本次员工工作流已预先生成了以下真实可执行 ESkill（Python 脚本），你必须在画布中按顺序串接它们：\n{lines}\n规则：\n- 对每个预置 Skill，在 workflow.nodes 中生成一个 node_type="eskill" 节点，config.skill_id 填写对应数字，config.output_var 填写对应 output_var。\n- 这些节点已在数据库中，不需要在 skill_blueprints 中重复定义。\n- 可在这些节点前后增加 condition / variable_set / start / end，但不得删除任何预置节点。\n- 推荐链路：start -> eskill(1) -> eskill(2) -> … -> end。\n'
    user_msg = f"工作流名称: {wf.name}\n\n工作流说明与需求:\n{brief.strip()}\n\n{_facade()._eskill_catalog_lines(db, user)}\n\n{_facade()._catalog_lines()}\n\n{employee_node_requirements}{preset_requirements}请先生成 skill_blueprints（仅新增不在上面「重要约束」中的 Skill），再生成 workflow.nodes 与 workflow.edges JSON。"
    msgs = [
        {"role": "system", "content": _facade().SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    if status_hook:
        try:
            maybe = status_hook(f"正在调用 {prov}/{mdl} 生成画布节点与边…")
            if hasattr(maybe, "__await__"):
                await maybe
        except RECOVERABLE_ERRORS:
            pass
    result = await _facade().chat_dispatch_via_session(
        db, user.id, prov, mdl, msgs, max_tokens=4096
    )
    if status_hook:
        try:
            maybe = status_hook("解析模型响应、组装节点与边…")
            if hasattr(maybe, "__await__"):
                await maybe
        except RECOVERABLE_ERRORS:
            pass
    if not result.get("ok"):
        e = str(result.get("error") or "LLM 调用失败")
        if "missing api key" in e.lower():
            e = "该供应商未配置可用 API Key（平台或 BYOK）"
        return {"ok": False, "error": e}
    data = _facade()._extract_json_object(str(result.get("content") or ""))
    if not data:
        return {"ok": False, "error": "模型返回无法解析为 JSON 对象"}
    workflow_data = data.get("workflow") if isinstance(data.get("workflow"), dict) else data
    raw_nodes = workflow_data.get("nodes") if isinstance(workflow_data, dict) else None
    raw_edges = workflow_data.get("edges") if isinstance(workflow_data, dict) else None
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return {
            "ok": False,
            "error": "JSON 须包含 workflow.nodes/workflow.edges 或 nodes/edges 数组",
        }
    warnings: _facade().List[str] = []
    skill_blueprints = _facade()._normalize_skill_blueprints(data, warnings)
    nodes_in: _facade().List[_facade().Dict[str, _facade().Any]] = []
    seen_tid: set[str] = set()
    for i, rn in enumerate(raw_nodes):
        if not isinstance(rn, dict):
            continue
        if len(nodes_in) >= _facade()._MAX_NODES:
            warnings.append(f"节点超过 {_facade()._MAX_NODES} 个，已截断")
            break
        nn = _facade()._normalize_node(rn, warnings)
        if not nn:
            continue
        if nn["temp_id"] in seen_tid:
            warnings.append(f"重复 temp_id {nn['temp_id']!r}，已跳过后续")
            continue
        seen_tid.add(nn["temp_id"])
        nodes_in.append(nn)
    employee_pack_id = str(target_employee_pack_id or "").strip()
    if employee_pack_id:
        employee_nodes = [n for n in nodes_in if n["node_type"] == "employee"]
        if employee_nodes:
            first_cfg = dict(employee_nodes[0].get("config") or {})
            first_cfg["employee_id"] = employee_pack_id
            if target_employee_label and (not str(employee_nodes[0].get("name") or "").strip()):
                employee_nodes[0]["name"] = str(target_employee_label)[:120]
            if not str(first_cfg.get("task") or "").strip():
                first_cfg["task"] = str(brief or "根据工作流上下文完成员工任务")[:400]
            employee_nodes[0]["config"] = first_cfg
            for extra in employee_nodes[1:]:
                extra_cfg = dict(extra.get("config") or {})
                if not str(extra_cfg.get("employee_id") or "").strip():
                    extra_cfg["employee_id"] = employee_pack_id
                extra["config"] = extra_cfg
        else:
            nodes_in.append(
                {
                    "temp_id": "target_employee",
                    "node_type": "employee",
                    "name": str(target_employee_label or "执行员工")[:120],
                    "config": {
                        "employee_id": employee_pack_id,
                        "task": str(brief or "根据工作流上下文完成员工任务")[:400],
                    },
                    "position_x": 260.0,
                    "position_y": 120.0,
                }
            )
            warnings.append("模型未生成 employee 节点，已自动插入目标员工包节点")
    temp_to_row: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {
        n["temp_id"]: n for n in nodes_in
    }
    edges_in: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        s = str(raw_edge.get("source_temp_id") or "").strip()
        t = str(raw_edge.get("target_temp_id") or "").strip()
        cond = str(raw_edge.get("condition") or "")
        if not s or not t or s not in temp_to_row or (t not in temp_to_row):
            warnings.append(f"跳过无效边: {s!r} -> {t!r}")
            continue
        edges_in.append({"source_temp_id": s, "target_temp_id": t, "condition": cond})
    if preset_nodes:
        existing_skill_ids = {
            str(
                n.get("config", {}).get("skill_id")
                or n.get("config", {}).get("temp_skill_id")
                or ""
            )
            for n in nodes_in
            if n.get("node_type") == "eskill"
        }
        missing_presets = [
            p
            for p in preset_nodes
            if str(p["eskill_id"]) not in existing_skill_ids
            and str(p.get("temp_skill_id") or "") not in existing_skill_ids
        ]
        if missing_presets:
            warnings.append(f"LLM 漏掉 {len(missing_presets)} 个预置 ESkill 节点，已自动插入")
            for idx_p, p in enumerate(missing_presets):
                tid = f"preset_eskill_{p['eskill_id']}"
                if tid in seen_tid:
                    continue
                seen_tid.add(tid)
                nodes_in.append(
                    {
                        "temp_id": tid,
                        "node_type": "eskill",
                        "name": str(p["name"])[:120],
                        "config": {
                            "skill_id": str(p["eskill_id"]),
                            "output_var": str(p.get("output_var") or "vibe_result"),
                            "task": str(p.get("name") or "")[:200],
                            "input_mapping": {},
                            "quality_gate": {},
                            "trigger_policy": {},
                            "force_dynamic": False,
                            "solidify": True,
                        },
                        "position_x": 260.0 + idx_p * 240.0,
                        "position_y": 240.0,
                    }
                )
        temp_to_row = {n["temp_id"]: n for n in nodes_in}
        inserted_preset_tids = [
            f"preset_eskill_{p['eskill_id']}"
            for p in missing_presets
            if f"preset_eskill_{p['eskill_id']}" in seen_tid
        ]
        if inserted_preset_tids:
            start_tid = next((n["temp_id"] for n in nodes_in if n["node_type"] == "start"), "")
            end_tid = next((n["temp_id"] for n in nodes_in if n["node_type"] == "end"), "")
            if start_tid and end_tid:
                edges_in = [
                    e
                    for e in edges_in
                    if not (e["source_temp_id"] == start_tid and e["target_temp_id"] == end_tid)
                ]
                chain = inserted_preset_tids
                prev = start_tid
                for tid in chain:
                    if not any((e["target_temp_id"] == tid for e in edges_in)):
                        edges_in.append(
                            {
                                "source_temp_id": prev,
                                "target_temp_id": tid,
                                "condition": "",
                            }
                        )
                    prev = tid
                if not any(
                    (
                        e["source_temp_id"] == prev and e["target_temp_id"] == end_tid
                        for e in edges_in
                    )
                ):
                    edges_in.append(
                        {
                            "source_temp_id": prev,
                            "target_temp_id": end_tid,
                            "condition": "",
                        }
                    )
    starts = [n for n in nodes_in if n["node_type"] == "start"]
    ends = [n for n in nodes_in if n["node_type"] == "end"]
    if len(starts) != 1 or len(ends) != 1:
        return {
            "ok": False,
            "error": f"图中须有且仅有一个 start 与一个 end（当前 start={len(starts)} end={len(ends)}）",
        }
    if employee_pack_id and any((n["temp_id"] == "target_employee" for n in nodes_in)):
        start_tid = next((n["temp_id"] for n in nodes_in if n["node_type"] == "start"), "")
        end_tid = next((n["temp_id"] for n in nodes_in if n["node_type"] == "end"), "")
        if start_tid and end_tid:
            edges_in = [
                e
                for e in edges_in
                if not (e["source_temp_id"] == start_tid and e["target_temp_id"] == end_tid)
            ]
            if not any((e["target_temp_id"] == "target_employee" for e in edges_in)):
                edges_in.append(
                    {
                        "source_temp_id": start_tid,
                        "target_temp_id": "target_employee",
                        "condition": "",
                    }
                )
            if not any((e["source_temp_id"] == "target_employee" for e in edges_in)):
                edges_in.append(
                    {
                        "source_temp_id": "target_employee",
                        "target_temp_id": end_tid,
                        "condition": "",
                    }
                )
    if not edges_in:
        return {"ok": False, "error": "未生成任何有效边"}
    cycles = _facade()._detect_cycles_nl(nodes_in, edges_in)
    if cycles:
        warnings.append(f"检测到环路（示例）: {cycles[0][:240]}")
    unreachable = _facade()._unreachable_from_start_nl(nodes_in, edges_in)
    if unreachable:
        warnings.append(f"存在从 start 不可达的节点 temp_id（至多列 5 个）: {unreachable[:5]}")
    skill_refs = {
        str(n.get("config", {}).get("temp_skill_id") or "")
        for n in nodes_in
        if n.get("node_type") == "eskill" and str(n.get("config", {}).get("temp_skill_id") or "")
    }
    blueprint_refs = {str(bp.get("temp_skill_id") or "") for bp in skill_blueprints}
    preset_name_to_skill = {
        str(p.get("name") or "").strip(): str(p.get("eskill_id") or "").strip()
        for p in preset_nodes
        if str(p.get("name") or "").strip() and str(p.get("eskill_id") or "").strip()
    }
    preset_alias_refs: set[str] = set()
    if preset_nodes and len(preset_nodes) == 1:
        preset_alias_refs = set(skill_refs)
    if preset_name_to_skill or preset_alias_refs:
        sole_preset_skill_id = (
            str(preset_nodes[0].get("eskill_id") or "").strip()
            if preset_nodes and len(preset_nodes) == 1
            else ""
        )
        for n in nodes_in:
            if n.get("node_type") != "eskill":
                continue
            cfg = n.get("config") if isinstance(n.get("config"), dict) else {}
            temp_skill_id = str(cfg.get("temp_skill_id") or "")
            if temp_skill_id in blueprint_refs or str(cfg.get("skill_id") or "").strip():
                if temp_skill_id not in preset_alias_refs:
                    continue
            preset_skill_id = preset_name_to_skill.get(str(n.get("name") or "").strip()) or (
                sole_preset_skill_id if temp_skill_id in preset_alias_refs else ""
            )
            if preset_skill_id:
                cfg.pop("temp_skill_id", None)
                cfg["skill_id"] = preset_skill_id
                n["config"] = cfg
                skill_refs.discard(temp_skill_id)
        if preset_alias_refs:
            skill_blueprints = [
                bp
                for bp in skill_blueprints
                if str(bp.get("temp_skill_id") or "") not in preset_alias_refs
            ]
            blueprint_refs = {str(bp.get("temp_skill_id") or "") for bp in skill_blueprints}
    missing_refs = sorted((x for x in skill_refs if x and x not in blueprint_refs))
    if missing_refs:
        return {
            "ok": False,
            "error": f"ESkill 节点引用了不存在的 temp_skill_id: {', '.join(missing_refs)}",
        }
    if status_hook:
        try:
            maybe = status_hook("正在创建 AI 生成的 Skill…")
            if hasattr(maybe, "__await__"):
                await maybe
        except RECOVERABLE_ERRORS:
            pass
    id_map: _facade().Dict[str, int] = {}
    temp_to_skill: _facade().Dict[str, int] = {}
    try:
        temp_to_skill = _facade()._create_generated_skills(db, user, skill_blueprints, warnings)
        for n in nodes_in:
            cfg = dict(n["config"])
            if n["node_type"] == "eskill":
                temp_skill_id = str(cfg.pop("temp_skill_id", "") or "")
                if temp_skill_id and (not str(cfg.get("skill_id") or "").strip()):
                    skill_id = temp_to_skill.get(temp_skill_id)
                    if not skill_id:
                        raise ValueError(f"未能创建或映射 Skill: {temp_skill_id}")
                    cfg["skill_id"] = str(skill_id)
                if not str(cfg.get("skill_id") or "").strip():
                    raise ValueError(f"ESkill 节点 {n['name']!r} 缺少 skill_id")
            row = _facade().WorkflowNode(
                workflow_id=workflow_id,
                node_type=n["node_type"],
                name=n["name"],
                config=_facade().json.dumps(cfg, ensure_ascii=False),
                position_x=n["position_x"],
                position_y=n["position_y"],
            )
            db.add(row)
            db.flush()
            id_map[n["temp_id"]] = row.id
        for e in edges_in:
            sid = id_map.get(e["source_temp_id"])
            tid = id_map.get(e["target_temp_id"])
            if not sid or not tid:
                continue
            db.add(
                _facade().WorkflowEdge(
                    workflow_id=workflow_id,
                    source_node_id=sid,
                    target_node_id=tid,
                    condition=e["condition"] or "",
                )
            )
        db.commit()
    except RECOVERABLE_ERRORS as ex:
        db.rollback()
        return {"ok": False, "error": f"写入节点/边失败: {ex}"}
    report = _facade().run_workflow_sandbox(
        workflow_id, {}, mock_employees=True, validate_only=True
    )
    errs = [str(x) for x in report.get("errors") or []]
    val_ok = bool(report.get("ok"))
    return {
        "ok": True,
        "nodes_created": len(nodes_in),
        "edges_created": len(edges_in),
        "sandbox_ok": val_ok,
        "validation_errors": errs,
        "llm_warnings": warnings,
        "skills_created": len(temp_to_skill),
        "skill_ids": temp_to_skill,
    }
