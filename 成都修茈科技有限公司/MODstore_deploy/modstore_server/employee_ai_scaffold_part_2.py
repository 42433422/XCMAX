# ruff: noqa
# mypy: ignore-errors
"""Employee scaffold helpers split by generation responsibility."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_ai_scaffold")


def _strip_json_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = _facade().re.sub("^```(?:json)?\\s*", "", t, flags=_facade().re.I)
        t = _facade().re.sub("\\s*```\\s*$", "", t)
    return t.strip()


def parse_employee_pack_llm_json(
    content: str,
) -> _facade().Tuple[_facade().Optional[_facade().Dict[str, _facade().Any]], str]:
    raw = _facade()._strip_json_fence(content)
    try:
        data = _facade().json.loads(raw)
    except _facade().json.JSONDecodeError as e:
        return (None, f"模型返回非合法 JSON: {e}")
    if not isinstance(data, dict):
        return (None, "JSON 根须为对象")
    pid = str(data.get("id") or "").strip().lower()
    if not pid or not _facade()._ID_RE.match(pid):
        return (None, "id 无效：须匹配小写字母/数字/._- 且不以连字符开头")
    name = str(data.get("name") or pid).strip() or pid
    ver = str(data.get("version") or "1.0.0").strip() or "1.0.0"
    desc = str(data.get("description") or "").strip()
    emp_in = data.get("employee")
    if not isinstance(emp_in, dict):
        return (None, "须包含 employee 对象")
    eid = pid
    label = str(emp_in.get("label") or name).strip() or name
    caps_in = emp_in.get("capabilities")
    caps: _facade().List[str] = []
    if isinstance(caps_in, list):
        for x in caps_in:
            if isinstance(x, str) and x.strip():
                caps.append(x.strip())
    dept_preset = str(data.get("department_preset") or "").strip().lower() or None
    caps = _facade()._default_capabilities(
        pid=pid,
        name=name,
        description=desc,
        employee_id=eid,
        label=label,
        capabilities=caps,
        department_preset=dept_preset,
    )
    manifest: _facade().Dict[str, _facade().Any] = {
        "id": pid,
        "name": name,
        "version": ver,
        "author": "",
        "description": desc,
        "artifact": "employee_pack",
        "scope": "global",
        "dependencies": {"xcagi": ">=1.0.0"},
        "employee": {"id": eid, "label": label, "capabilities": caps},
    }
    v2_in = data.get("employee_config_v2")
    if isinstance(v2_in, dict):
        manifest["employee_config_v2"] = _facade()._normalize_employee_config_v2_for_canvas(
            v2_in,
            pid=pid,
            name=name,
            description=desc,
            employee_id=eid,
            label=label,
            capabilities=caps,
        )
    else:
        manifest["employee_config_v2"] = _facade()._default_employee_config_v2(
            pid=pid, name=name, description=desc, employee_id=eid, label=label, capabilities=caps
        )
    hp_raw = data.get("xcagi_host_profile")
    (hp_norm, hp_errs) = _facade().normalize_xcagi_host_profile(hp_raw)
    if hp_errs:
        return (None, "xcagi_host_profile: " + "; ".join(hp_errs))
    if hp_norm:
        manifest["xcagi_host_profile"] = hp_norm
    wf_row = _facade().merge_workflow_employee_for_manifest(
        employee_id=eid, label=label, panel_summary=desc, host_profile=hp_norm
    )
    wf_row["api_base_path"] = f"employees/{eid}"
    manifest["workflow_employees"] = [wf_row]
    manifest["backend"] = {"entry": "blueprints", "init": "mod_init"}
    ve = _facade().validate_manifest_dict(manifest)
    if ve:
        return (None, "manifest 校验: " + "; ".join(ve))
    return (manifest, "")


def _normalize_employee_config_v2_for_canvas(
    v2: _facade().Dict[str, _facade().Any],
    *,
    pid: str,
    name: str,
    description: str,
    employee_id: str,
    label: str,
    capabilities: _facade().List[str],
) -> _facade().Dict[str, _facade().Any]:
    """Guarantee the employee canvas modules have concrete editable fields.

    The LLM may return a sparse ``employee_config_v2``.  The workbench canvas,
    however, edits fixed module slices (identity, cognition.agent,
    cognition.skills, collaboration.workflow).  Fill those slices at generation
    time so the generated package itself is complete instead of relying on
    frontend recovery heuristics.
    """
    out = dict(v2 or {})
    identity = dict(out.get("identity") if isinstance(out.get("identity"), dict) else {})
    identity.update(
        {
            "id": pid,
            "version": str(identity.get("version") or "1.0.0").strip() or "1.0.0",
            "artifact": str(identity.get("artifact") or "employee_pack").strip() or "employee_pack",
            "name": str(identity.get("name") or name or label or employee_id).strip() or pid,
            "description": str(identity.get("description") or description).strip(),
        }
    )
    out["identity"] = identity
    cognition = dict(out.get("cognition") if isinstance(out.get("cognition"), dict) else {})
    agent = dict(cognition.get("agent") if isinstance(cognition.get("agent"), dict) else {})
    role = dict(agent.get("role") if isinstance(agent.get("role"), dict) else {})
    role.update(
        {
            "name": str(role.get("name") or label or name).strip() or pid,
            "persona": str(role.get("persona") or description or "专业、高效、亲切").strip(),
            "tone": str(role.get("tone") or "professional").strip() or "professional",
            "expertise": (
                role.get("expertise") if isinstance(role.get("expertise"), list) else capabilities
            ),
        }
    )
    model = dict(agent.get("model") if isinstance(agent.get("model"), dict) else {})
    model.update(
        {
            "provider": str(model.get("provider") or "auto").strip() or "auto",
            "model_name": str(model.get("model_name") or "auto").strip() or "auto",
            "temperature": model.get("temperature", 0.7),
            "max_tokens": model.get("max_tokens", 4000),
            "top_p": model.get("top_p", 0.9),
        }
    )
    agent.update(
        {
            "system_prompt": _facade()._normalize_employee_system_prompt(
                str(
                    agent.get("system_prompt")
                    or description
                    or f"你是员工助手：{label or name}。请根据用户输入完成任务，并输出结构化结果。"
                ).strip(),
                label=label or name,
                description=description,
            ),
            "role": role,
            "behavior_rules": _facade()._normalize_behavior_rules(
                agent.get("behavior_rules"), label=label or name, description=description
            ),
            "few_shot_examples": (
                agent.get("few_shot_examples")
                if isinstance(agent.get("few_shot_examples"), list)
                else []
            ),
            "model": model,
        }
    )
    cognition["agent"] = agent
    caps_norm = _facade()._default_capabilities(
        pid=pid,
        name=name,
        description=description,
        employee_id=employee_id,
        label=label,
        capabilities=capabilities,
    )
    if not isinstance(cognition.get("skills"), list) or not cognition.get("skills"):
        cognition["skills"] = _facade()._default_skill_entries(
            caps_norm, label=label or name, description=description
        )
    else:
        cognition["skills"] = _facade()._validate_skill_quality(
            cognition["skills"], label=label or name, description=description
        )
    out["cognition"] = cognition
    collaboration = dict(
        out.get("collaboration") if isinstance(out.get("collaboration"), dict) else {}
    )
    workflow = dict(
        collaboration.get("workflow") if isinstance(collaboration.get("workflow"), dict) else {}
    )
    workflow.setdefault("workflow_id", 0)
    workflow["name"] = str(workflow.get("name") or label or name or pid).strip() or pid
    collaboration["workflow"] = workflow
    out["collaboration"] = collaboration
    actions = dict(out.get("actions") if isinstance(out.get("actions"), dict) else {})
    raw_handlers = actions.get("handlers")
    actions["handlers"] = _facade()._normalize_action_handlers(raw_handlers)
    out["actions"] = actions
    out.setdefault("metadata", {"framework_version": "2.0.0", "created_by": "employee_ai_scaffold"})
    _facade()._ensure_seo_runtime_details(
        out, pid=pid, name=name, description=description, label=label or name
    )
    return out


def _normalize_employee_system_prompt(prompt: str, *, label: str, description: str) -> str:
    text = str(prompt or "").strip()
    banned_template = ("## 用途", "## 输入", "## 输出", "## 示例")
    if not text or all((marker in text for marker in banned_template)):
        role = str(label or "员工助手").strip() or "员工助手"
        desc = str(description or "根据用户输入完成任务").strip()
        return f"你是{role}。你的职责是：{desc}。\n工作时先判断用户目标和可用上下文，只使用输入中给出的事实与工具结果；信息不足时先说明缺口并给出可继续推进的最小问题。\n输出应直接服务任务：先给结论或执行结果，再给必要依据、步骤和下一步建议。不得编造来源、数据、执行结果或不存在的系统能力。"
    return text


def _normalize_behavior_rules(
    raw: _facade().Any, *, label: str, description: str
) -> _facade().List[str]:
    if isinstance(raw, list):
        rules = [str(x).strip() for x in raw if str(x).strip()]
        if rules:
            cleaned: _facade().List[str] = []
            for rule in rules:
                if len(rule) > 120:
                    rule = rule[:117].rstrip() + "…"
                cleaned.append(rule)
            return cleaned[:8]
    role = str(label or "当前员工").strip()
    task = str(description or "用户任务").strip()
    if len(task) > 72:
        task = task[:69].rstrip() + "…"
    return [
        f"始终围绕{role}的职责范围处理请求。",
        "优先使用 input 中提供的 manifest_signals / role_context / yuangon 节选作答；缺口用「待确认」标注，不要补造缺失事实。",
        "当输入不足、工具失败或结论不确定时，明确说明原因和需要补充的信息。",
        "输出保持结构化、可执行，避免泛泛而谈。",
    ]


def _default_employee_config_v2(
    *,
    pid: str,
    name: str,
    description: str,
    employee_id: str,
    label: str,
    capabilities: _facade().List[str],
) -> _facade().Dict[str, _facade().Any]:
    text = " ".join([pid, name, description, employee_id, label, " ".join(capabilities)]).lower()
    wants_rankings = any(
        (k in text for k in ("排行", "rank", "leaderboard", "模型", "model", "上网", "联网"))
    )
    perception: _facade().Dict[str, _facade().Any] = {
        "type": "web_rankings" if wants_rankings else "text"
    }
    prompt = (
        "你是 AI 模型排行榜统计员工。请基于输入中的网页抓取片段，整理主流 AI 模型的排名、模型名称、来源网站和简短结论；如果某来源抓取失败，要明确列出失败来源，不要编造未出现在片段中的排名。"
        if wants_rankings
        else _facade()._normalize_employee_system_prompt(
            "", label=label or name, description=description
        )
    )
    return {
        "identity": {
            "id": pid,
            "version": "1.0.0",
            "artifact": "employee_pack",
            "name": name,
            "description": description,
        },
        "perception": perception,
        "memory": {"type": "session"},
        "cognition": {
            "agent": {
                "system_prompt": prompt,
                "role": {
                    "name": label or name,
                    "persona": description or "专业、高效、亲切",
                    "tone": "professional",
                    "expertise": capabilities,
                },
                "behavior_rules": _facade()._normalize_behavior_rules(
                    [], label=label or name, description=description
                ),
                "few_shot_examples": [],
                "model": {
                    "provider": "auto",
                    "model_name": "auto",
                    "temperature": 0.2,
                    "max_tokens": 4000,
                    "top_p": 0.9,
                },
            },
            "skills": _facade()._default_skill_entries(
                capabilities, label=label or name, description=description
            ),
        },
        "collaboration": {"workflow": {"workflow_id": 0, "name": label or name or pid}},
        "actions": {
            "handlers": ["direct_python"],
            "direct_python": {
                "module": _facade().sanitize_employee_stem(employee_id),
                "action": "convert",
                "default_output_relpath": "outputs/employee_output.xlsx",
                "default_template_relpath": "",
                "default_use_personnel_roster": True,
            },
        },
        "metadata": {"framework_version": "2.0.0", "created_by": "employee_ai_scaffold"},
    }


def append_employee_stub_files_to_zip(
    zf: _facade().zipfile.ZipFile, pack_id: str, manifest: _facade().Dict[str, _facade().Any]
) -> None:
    """写入 ``backend/employee_stubs`` 占位模块（与 workflow 脚手架一致，供安装包浏览 / XCAGI 对齐）。"""
    emp_id = pack_id
    safe = _facade().safe_stub_module_name(emp_id)
    base = f"{pack_id}/backend/employee_stubs".replace("\\", "/")
    zf.writestr(f"{base}/__init__.py", '"""Packaged employee route stubs."""\n')
    zf.writestr(f"{base}/{safe}.py", _facade().stub_module_body(emp_id, safe))


def build_employee_pack_zip(
    pack_id: str, manifest: _facade().Dict[str, _facade().Any], *, include_runtime: bool = True
) -> bytes:
    """manifest.zip：含 manifest.json；可选 ``backend/blueprints.py`` + ``backend/employees`` 运行时（与 FHD 挂载契约对齐）。"""
    import copy

    mf = copy.deepcopy(manifest)
    mf["id"] = pack_id
    if isinstance(mf.get("employee"), dict):
        mf["employee"]["id"] = pack_id
    for _row in mf.get("workflow_employees") or []:
        if isinstance(_row, dict):
            _row["id"] = pack_id
    body = _facade().json.dumps(mf, ensure_ascii=False, indent=2) + "\n"
    buf = _facade().io.BytesIO()
    emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    eid = pack_id
    stem = _facade().sanitize_employee_stem(eid)
    label = str(emp.get("label") or eid).strip()
    with _facade().zipfile.ZipFile(buf, "w", _facade().zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{pack_id}/manifest.json", body)
        if include_runtime:
            bp = _facade().render_employee_pack_blueprints_py(
                pack_id=pack_id, employee_id=eid, stem=stem, label=label
            )
            zf.writestr(f"{pack_id}/backend/blueprints.py", bp)
            emp_py = _facade().render_employee_pack_employee_py(
                employee_id=eid, stem=stem, label=label
            )
            zf.writestr(f"{pack_id}/backend/employees/{stem}.py", emp_py)
            zf.writestr(
                f"{pack_id}/backend/employees/__init__.py",
                '"""Generated employee implementations (employee_pack)."""\n',
            )
        else:
            _facade().append_employee_stub_files_to_zip(zf, pack_id, manifest)
    return buf.getvalue()


def normalize_editor_manifest_for_registry(
    mf: _facade().Dict[str, _facade().Any], pack_id: str
) -> _facade().Tuple[_facade().Dict[str, _facade().Any], _facade().List[str]]:
    """画布形态 manifest → 登记级 manifest（补顶层字段、employee 对象、backend）。

    工作台编辑器把 ``identity``/``cognition``/… 放在根上（画布形态），
    而 ``validate_manifest_dict`` 要求顶层有 ``artifact``/``name``/``version``/
    ``employee`` 等字段（登记形态）。本函数做单向提升，**不修改**原对象，
    返回 (规范化后 manifest, 校验错误列表)。
    """
    import copy

    out = copy.deepcopy(mf)
    ident = out.get("identity") if isinstance(out.get("identity"), dict) else {}
    if not isinstance(out.get("artifact"), str) or not out["artifact"].strip():
        out["artifact"] = str(ident.get("artifact") or "employee_pack").strip() or "employee_pack"
    out["id"] = pack_id
    if isinstance(ident, dict):
        ident["id"] = pack_id
        out["identity"] = ident
    if not str(out.get("name") or "").strip():
        out["name"] = str(ident.get("name") or out["id"]).strip() or out["id"]
    if not str(out.get("version") or "").strip():
        out["version"] = str(ident.get("version") or "1.0.0").strip() or "1.0.0"
    if not str(out.get("description") or "").strip():
        out["description"] = str(ident.get("description") or "").strip()
    out.setdefault("scope", "global")
    out.setdefault("backend", {"entry": "blueprints", "init": "mod_init"})
    if not isinstance(out.get("employee"), dict):
        eid = pack_id
        label = str(ident.get("name") or out.get("name") or eid).strip() or eid
        cognition = out.get("cognition") if isinstance(out.get("cognition"), dict) else {}
        caps: _facade().List[str] = []
        for sk in cognition.get("skills") or []:
            if isinstance(sk, dict):
                n = str(sk.get("name") or sk.get("skill_id") or "").strip()
                if n:
                    caps.append(n)
        caps = _facade()._default_capabilities(
            pid=str(out.get("id") or pack_id),
            name=str(out.get("name") or ""),
            description=str(out.get("description") or ""),
            employee_id=eid,
            label=label,
            capabilities=caps,
        )
        out["employee"] = {"id": eid, "label": label, "capabilities": caps}
    else:
        emp_obj = out["employee"]
        emp_obj["id"] = pack_id
        emp_obj.setdefault("label", str(out.get("name") or pack_id))
        emp_caps = (
            emp_obj.get("capabilities") if isinstance(emp_obj.get("capabilities"), list) else []
        )
        emp_obj["capabilities"] = _facade()._default_capabilities(
            pid=str(out.get("id") or pack_id),
            name=str(out.get("name") or ""),
            description=str(out.get("description") or ""),
            employee_id=pack_id,
            label=str(emp_obj.get("label") or out.get("name") or ""),
            capabilities=emp_caps,
        )
    if not isinstance(out.get("employee_config_v2"), dict):
        v2: _facade().Dict[str, _facade().Any] = {}
        for slice_key in (
            "identity",
            "cognition",
            "perception",
            "memory",
            "actions",
            "collaboration",
            "management",
            "metadata",
        ):
            if isinstance(out.get(slice_key), dict):
                v2[slice_key] = copy.deepcopy(out[slice_key])
        if v2:
            out["employee_config_v2"] = _facade()._normalize_employee_config_v2_for_canvas(
                v2,
                pid=out["id"],
                name=out["name"],
                description=out.get("description") or "",
                employee_id=pack_id,
                label=str((out.get("employee") or {}).get("label") or out["name"]),
                capabilities=(out.get("employee") or {}).get("capabilities") or [],
            )
    elif isinstance(out.get("employee_config_v2"), dict):
        emp_obj = out.get("employee") if isinstance(out.get("employee"), dict) else {}
        out["employee_config_v2"] = _facade()._normalize_employee_config_v2_for_canvas(
            out["employee_config_v2"],
            pid=str(out.get("id") or pack_id),
            name=str(out.get("name") or pack_id),
            description=str(out.get("description") or ""),
            employee_id=pack_id,
            label=str(emp_obj.get("label") or out.get("name") or pack_id),
            capabilities=(
                emp_obj.get("capabilities") if isinstance(emp_obj.get("capabilities"), list) else []
            ),
        )
    if not out.get("workflow_employees"):
        wf_row = _facade().merge_workflow_employee_for_manifest(
            employee_id=str(out.get("id") or pack_id),
            label=str((out.get("employee") or {}).get("label") or out["name"]),
            panel_summary=out.get("description") or "",
            host_profile=None,
        )
        out["workflow_employees"] = [wf_row]
    elif isinstance(out.get("workflow_employees"), list):
        emp_obj = out.get("employee") if isinstance(out.get("employee"), dict) else {}
        eid = str(out.get("id") or pack_id).strip() or pack_id
        for row in out["workflow_employees"]:
            if not isinstance(row, dict):
                continue
            row["id"] = eid
            row.setdefault("label", str(emp_obj.get("label") or out.get("name") or eid))
            row.setdefault(
                "panel_title",
                row.get("label") or str(emp_obj.get("label") or out.get("name") or eid),
            )
            row["api_base_path"] = f"employees/{eid}"
    errs = _facade().validate_manifest_dict(out)
    return (out, errs)
