# ruff: noqa
# mypy: ignore-errors
"""Normalization and persistence operations for natural-language workflow graphs."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workflow_nl_graph")


def _default_static_logic(
    name: str, output_var: str = "result"
) -> _facade().Dict[str, _facade().Any]:
    return {
        "type": "template_transform",
        "template": f"{name}: " + "${value}",
        "dynamic_template": f"{name}: " + "${value}；补充信息：${details}",
        "fallback_template": f"{name}: " + "${value}",
        "output_var": output_var or "result",
        "metadata": {
            "repair_hints": ["补齐缺失输入后重试", "质量不足时追加 details 生成更完整结果"],
            "failure_modes": ["missing_field", "quality_below_threshold", "runtime_error"],
        },
    }


def _sanitize_static_logic(
    raw: _facade().Any, name: str, warnings: _facade().List[str]
) -> _facade().Dict[str, _facade().Any]:
    logic = _facade()._safe_dict(raw)
    if not logic:
        return _facade()._default_static_logic(name)
    logic_type = str(logic.get("type") or "template_transform").strip()
    if logic_type not in {"template_transform", "pipeline", "employee_task"}:
        warnings.append(
            f"Skill {name!r} static_logic.type={logic_type!r} 不支持，已改为 template_transform"
        )
        return _facade()._default_static_logic(name, str(logic.get("output_var") or "result"))
    if logic_type == "template_transform":
        output_var = str(logic.get("output_var") or "result").strip() or "result"
        template = str(logic.get("template") or f"{name}: " + "${value}")
        sanitized = {"type": "template_transform", "template": template, "output_var": output_var}
        required = logic.get("required_fields")
        if isinstance(required, list):
            sanitized["required_fields"] = [str(x) for x in required if str(x).strip()]
        domain_keywords = logic.get("domain_keywords")
        if isinstance(domain_keywords, list):
            sanitized["domain_keywords"] = [str(x) for x in domain_keywords if str(x).strip()]
        dynamic_template = logic.get("dynamic_template")
        if isinstance(dynamic_template, str) and dynamic_template.strip():
            sanitized["dynamic_template"] = dynamic_template
        fallback_template = logic.get("fallback_template")
        if isinstance(fallback_template, str) and fallback_template.strip():
            sanitized["fallback_template"] = fallback_template
        if "allow_steps" in logic:
            sanitized["allow_steps"] = _facade()._safe_bool(logic.get("allow_steps"), False)
        metadata = logic.get("metadata")
        if isinstance(metadata, dict):
            sanitized["metadata"] = metadata
        repair_hints = logic.get("repair_hints")
        if isinstance(repair_hints, list):
            sanitized.setdefault("metadata", {})["repair_hints"] = [
                str(x) for x in repair_hints if str(x).strip()
            ]
        failure_modes = logic.get("failure_modes")
        if isinstance(failure_modes, list):
            sanitized.setdefault("metadata", {})["failure_modes"] = [
                str(x) for x in failure_modes if str(x).strip()
            ]
        return sanitized
    if logic_type == "employee_task":
        employee_id = str(logic.get("employee_id") or "").strip()
        if not employee_id:
            warnings.append(
                f"Skill {name!r} 缺少 employee_id，employee_task 已降级为 template_transform"
            )
            return _facade()._default_static_logic(name, str(logic.get("output_var") or "result"))
        return {
            "type": "employee_task",
            "employee_id": employee_id,
            "task_template": str(logic.get("task_template") or logic.get("task") or name),
            "output_var": str(logic.get("output_var") or "employee_result"),
        }
    steps_in = logic.get("steps")
    if not isinstance(steps_in, list) or not steps_in:
        warnings.append(f"Skill {name!r} pipeline 缺少 steps，已改为 template_transform")
        return _facade()._default_static_logic(name, str(logic.get("output_var") or "result"))
    steps: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for idx, step in enumerate(steps_in[:12]):
        if not isinstance(step, dict):
            continue
        step_type = str(step.get("type") or "template_transform").strip()
        output_var = str(step.get("output_var") or step.get("id") or f"step_{idx}").strip()
        if step_type == "template_transform":
            steps.append(
                {
                    "id": str(step.get("id") or output_var),
                    "type": "template_transform",
                    "template": str(step.get("template") or "${value}"),
                    "output_var": output_var or f"step_{idx}",
                }
            )
        elif step_type == "set_value":
            steps.append(
                {
                    "id": str(step.get("id") or output_var),
                    "type": "set_value",
                    "value": step.get("value"),
                    "output_var": output_var or f"step_{idx}",
                }
            )
        elif step_type == "employee_task" and str(step.get("employee_id") or "").strip():
            steps.append(
                {
                    "id": str(step.get("id") or output_var),
                    "type": "employee_task",
                    "employee_id": str(step.get("employee_id") or "").strip(),
                    "task_template": str(step.get("task_template") or step.get("task") or name),
                    "output_var": output_var or f"step_{idx}",
                }
            )
        else:
            warnings.append(
                f"Skill {name!r} pipeline step #{idx} 类型 {step_type!r} 不可用，已跳过"
            )
    if not steps:
        return _facade()._default_static_logic(name, str(logic.get("output_var") or "result"))
    return {"type": "pipeline", "steps": steps}


def _normalize_skill_blueprints(
    data: _facade().Dict[str, _facade().Any], warnings: _facade().List[str]
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    raw = data.get("skill_blueprints")
    if raw is None:
        raw = data.get("skills")
    if not isinstance(raw, list):
        return []
    out: _facade().List[_facade().Dict[str, _facade().Any]] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw[: _facade()._MAX_SKILL_BLUEPRINTS]):
        if not isinstance(item, dict):
            continue
        temp_id = _facade()._as_identifier(
            item.get("temp_skill_id") or item.get("id"), f"skill_{idx + 1}"
        )
        if temp_id in seen:
            warnings.append(f"重复 temp_skill_id {temp_id!r}，已跳过")
            continue
        seen.add(temp_id)
        name = str(item.get("name") or temp_id).strip()[:128] or temp_id
        out.append(
            {
                "temp_skill_id": temp_id,
                "name": name,
                "domain": str(item.get("domain") or "").strip()[:2000],
                "description": str(item.get("description") or "").strip()[:4000],
                "static_logic": _facade()._sanitize_static_logic(
                    item.get("static_logic"), name, warnings
                ),
                "quality_gate": _facade()._safe_dict(item.get("quality_gate")),
                "trigger_policy": {
                    "on_error": True,
                    "on_quality_below_threshold": True,
                    **_facade()._safe_dict(item.get("trigger_policy")),
                },
            }
        )
    return out


def _create_generated_skills(
    db: _facade().Session,
    user: _facade().User,
    blueprints: _facade().List[_facade().Dict[str, _facade().Any]],
    warnings: _facade().List[str],
) -> _facade().Dict[str, int]:
    temp_to_skill: _facade().Dict[str, int] = {}
    for bp in blueprints:
        temp_id = str(bp.get("temp_skill_id") or "").strip()
        name = str(bp.get("name") or temp_id or "Generated Skill").strip()[:128]
        if not temp_id:
            continue
        existing = (
            db.query(_facade().ESkill)
            .filter(_facade().ESkill.user_id == user.id, _facade().ESkill.name == name)
            .first()
        )
        if existing:
            temp_to_skill[temp_id] = int(existing.id)
            warnings.append(f"Skill {name!r} 已存在，复用 skill_id={existing.id}")
            continue
        skill = _facade().ESkill(
            user_id=user.id,
            name=name,
            domain=str(bp.get("domain") or ""),
            description=str(bp.get("description") or ""),
            active_version=1,
        )
        db.add(skill)
        db.flush()
        version = _facade().ESkillVersion(
            eskill_id=skill.id,
            version=1,
            static_logic_json=_facade()._dumps(
                bp.get("static_logic") or _facade()._default_static_logic(name)
            ),
            trigger_policy_json=_facade()._dumps(bp.get("trigger_policy") or {}),
            quality_gate_json=_facade()._dumps(bp.get("quality_gate") or {}),
            note="ai generated from workflow",
        )
        db.add(version)
        temp_to_skill[temp_id] = int(skill.id)
    return temp_to_skill


def _normalize_node(
    raw: _facade().Dict[str, _facade().Any], warnings: _facade().List[str]
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    tid = str(raw.get("temp_id") or "").strip()
    nt = str(raw.get("node_type") or "").strip().lower()
    name = str(raw.get("name") or "").strip() or nt
    if not tid or nt not in _facade()._ALLOWED_TYPES:
        warnings.append(f"跳过非法节点: temp_id={tid!r} type={nt!r}")
        return None
    cfg = raw.get("config")
    if not isinstance(cfg, dict):
        cfg = {}
    if nt == "employee":
        eid = str(cfg.get("employee_id") or "").strip()
        task = str(cfg.get("task") or "").strip()
        if not eid:
            warnings.append(f"员工节点 {name!r} 缺少 employee_id，已用占位 placeholder")
            eid = "placeholder"
            cfg = {**cfg, "employee_id": eid}
        if not task:
            task = "根据工作流上下文完成用户描述中的任务"
            cfg = {**cfg, "task": task}
            warnings.append(f"员工节点 {name!r} 已补全默认 task")
    elif nt == "eskill":
        raw_skill_id = cfg.get("skill_id") or cfg.get("eskill_id")
        skill_id = str(raw_skill_id or "").strip()
        if skill_id:
            try:
                skill_id = str(int(skill_id))
            except (TypeError, ValueError):
                warnings.append(
                    f"ESkill 节点 {name!r} skill_id={skill_id!r} 不是数字，已清空并等待 temp_skill_id 映射"
                )
                skill_id = ""
        temp_skill_id = _facade()._as_identifier(
            cfg.get("temp_skill_id") or cfg.get("skill_ref") or cfg.get("temp_id"), ""
        )
        task = str(cfg.get("task") or "").strip()
        output_var = str(cfg.get("output_var") or "eskill_output").strip() or "eskill_output"
        input_mapping = cfg.get("input_mapping")
        if not isinstance(input_mapping, dict):
            input_mapping = {}
        normalized_cfg: _facade().Dict[str, _facade().Any] = {
            "task": task,
            "output_var": output_var,
            "input_mapping": input_mapping,
            "quality_gate": _facade()._safe_dict(cfg.get("quality_gate")),
            "trigger_policy": _facade()._safe_dict(cfg.get("trigger_policy")),
            "force_dynamic": _facade()._safe_bool(cfg.get("force_dynamic"), False),
            "solidify": _facade()._safe_bool(cfg.get("solidify"), True),
        }
        if skill_id:
            normalized_cfg["skill_id"] = skill_id
        if temp_skill_id:
            normalized_cfg["temp_skill_id"] = temp_skill_id
        if not skill_id and (not temp_skill_id):
            warnings.append(f"ESkill 节点 {name!r} 缺少 skill_id/temp_skill_id")
        cfg = normalized_cfg
    elif nt == "condition":
        expr = str(cfg.get("expression") or "").strip()
        cfg = {"expression": expr} if expr else {}
    elif nt == "openapi_operation":
        try:
            cid = int(cfg.get("connector_id") or 0)
        except (TypeError, ValueError):
            cid = 0
        oid = str(cfg.get("operation_id") or "").strip()
        params = cfg.get("params")
        if not isinstance(params, dict):
            params = {}
        im = cfg.get("input_mapping")
        if isinstance(im, dict) and im:
            params = im
        out_var = str(cfg.get("output_var") or "api_result").strip() or "api_result"
        cfg = {
            "connector_id": cid,
            "operation_id": oid,
            "params": params,
            "input_mapping": params,
            "output_var": out_var,
        }
        if not cid:
            warnings.append(f"OpenAPI 节点 {name!r} 缺少有效 connector_id，已写 0，请在画布中修改")
        if not oid:
            warnings.append(f"OpenAPI 节点 {name!r} 缺少 operation_id，请在画布中补全")
    elif nt == "knowledge_search":
        query = str(cfg.get("query") or cfg.get("query_template") or "").strip()
        kb_id = str(cfg.get("kb_id") or "").strip()
        if not query and kb_id:
            query = f"知识库 {kb_id} 检索"
            warnings.append(f"知识检索节点 {name!r} 已根据 kb_id 生成占位 query")
        if not query:
            query = "根据上下文检索知识库"
            warnings.append(f"知识检索节点 {name!r} 已补全默认 query")
        try:
            top_k = int(cfg.get("top_k") or 5)
        except (TypeError, ValueError):
            top_k = 5
        output_var = str(cfg.get("output_var") or "kb_chunks").strip() or "kb_chunks"
        cids = cfg.get("collection_ids")
        if not isinstance(cids, list):
            cids = []
        cfg = {
            "query": query,
            "top_k": max(1, min(50, top_k)),
            "output_var": output_var,
            "collection_ids": cids,
        }
        if kb_id:
            cfg["kb_id"] = kb_id
    elif nt == "webhook_trigger":
        secret = str(cfg.get("secret") or "").strip()
        payload_var = str(cfg.get("payload_var") or "webhook_payload").strip() or "webhook_payload"
        cfg = {"secret": secret, "payload_var": payload_var}
    elif nt == "cron_trigger":
        cron = str(cfg.get("cron") or "0 * * * *").strip() or "0 * * * *"
        tz = str(cfg.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"
        cfg = {"cron": cron, "timezone": tz}
    elif nt == "variable_set":
        vname = str(cfg.get("name") or "").strip()
        value = cfg.get("value", "")
        if value is not None and (not isinstance(value, (dict, list))):
            value = str(value)
        if not vname:
            warnings.append(f"变量赋值节点 {name!r} 缺少 name，已用占位 _var")
            vname = "_var"
        cfg = {"name": vname, "value": value}
    elif nt in ("start", "end"):
        cfg = {}
    else:
        cfg = {}
    try:
        px = float(raw.get("position_x", 0))
        py = float(raw.get("position_y", 0))
    except (TypeError, ValueError):
        (px, py) = (0.0, 0.0)
    return {
        "temp_id": tid,
        "node_type": nt,
        "name": name[:256],
        "config": cfg,
        "position_x": px,
        "position_y": py,
    }


def _detect_cycles_nl(
    nodes_in: _facade().List[_facade().Dict[str, _facade().Any]],
    edges_in: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().List[str]:
    """基于 temp_id 的有向图环路检测（DFS 三色）。"""
    node_ids = {n["temp_id"] for n in nodes_in}
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for e in edges_in:
        src = str(e.get("source_temp_id") or "").strip()
        tgt = str(e.get("target_temp_id") or "").strip()
        if src in adj and tgt in node_ids:
            adj[src].append(tgt)
    (WHITE, GRAY, BLACK) = (0, 1, 2)
    color: dict[str, int] = {nid: WHITE for nid in node_ids}
    cycles: _facade().List[str] = []

    def dfs(u: str, path: _facade().List[str]) -> None:
        color[u] = GRAY
        path.append(u)
        for v in adj.get(u, []):
            if v not in node_ids:
                continue
            vc = color.get(v, WHITE)
            if vc == GRAY:
                try:
                    idx = path.index(v)
                    cycles.append(" → ".join(path[idx:] + [v]))
                except ValueError:
                    cycles.append(f"cycle near {u!r} -> {v!r}")
            elif vc == WHITE:
                dfs(v, path)
        path.pop()
        color[u] = BLACK

    for nid in node_ids:
        if color.get(nid) == WHITE:
            dfs(nid, [])
    return cycles


def _unreachable_from_start_nl(
    nodes_in: _facade().List[_facade().Dict[str, _facade().Any]],
    edges_in: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().List[str]:
    """从 node_type=start 的节点出发 BFS，返回不可达的 temp_id。"""
    start_ids = [n["temp_id"] for n in nodes_in if n.get("node_type") == "start"]
    node_ids = {n["temp_id"] for n in nodes_in}
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for e in edges_in:
        src = str(e.get("source_temp_id") or "").strip()
        tgt = str(e.get("target_temp_id") or "").strip()
        if src in adj and tgt in node_ids:
            adj[src].append(tgt)
    if not start_ids:
        return []
    visited: set[str] = set()
    q: _facade().deque[str] = _facade().deque(start_ids)
    while q:
        u = q.popleft()
        if u in visited:
            continue
        visited.add(u)
        for v in adj.get(u, []):
            if v not in visited:
                q.append(v)
    return [n["temp_id"] for n in nodes_in if n["temp_id"] not in visited]
