# mypy: disable-error-code="arg-type, dict-item, index, union-attr, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


def _normalize_manifest(
    manifest: _facade().Dict[str, _facade().Any],
    brief: str,
    rule_spec: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    fallback = _facade()._fallback_manifest(brief, rule_spec)
    out = dict(fallback)
    out.update({k: v for k, v in manifest.items() if k not in ("employee_config_v2",)})
    explicit_pid = _facade()._slug_from_brief(brief)
    pack_id_hint = str(rule_spec.get("pack_id") or "").strip()
    pid = (
        pack_id_hint
        or _facade().normalize_mod_id(str(explicit_pid or out.get("id") or fallback["id"]))
        or fallback["id"]
    )
    out["id"] = pid
    out["artifact"] = "employee_pack"
    out.setdefault("version", "1.0.0")
    out.setdefault("name", fallback["name"])
    emp = out.get("employee") if isinstance(out.get("employee"), dict) else {}
    fallback_emp = fallback["employee"] if isinstance(fallback.get("employee"), dict) else {}
    emp = {**fallback_emp, **emp, "id": pid}
    emp.setdefault("label", out.get("name") or pid)
    out["employee"] = emp
    rows = out.get("workflow_employees")
    if not isinstance(rows, list) or not rows:
        out["workflow_employees"] = fallback.get("workflow_employees") or []
    else:
        normalized_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            r = dict(row)
            r["id"] = pid
            r.setdefault("label", emp.get("label") or out.get("name") or r["id"])
            r.setdefault("api_base_path", f"employees/{r['id']}")
            r.setdefault("entry_action", "run")
            normalized_rows.append(r)
        out["workflow_employees"] = normalized_rows or fallback.get("workflow_employees") or []
    out["backend"] = {"entry": "blueprints", "init": "mod_init"}
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    merged_v2 = dict(fallback["employee_config_v2"])
    merged_v2.update(v2)
    actions = dict(merged_v2.get("actions") if isinstance(merged_v2.get("actions"), dict) else {})
    runtime_kind = rule_spec.get("runtime_kind") or "generic_excel_transform"
    _is_doc_review = runtime_kind in ("contract_doc_review", "doc_template_transform")
    if _is_doc_review:
        actions["handlers"] = ["agent"]
        actions.pop("direct_python", None)
    else:
        direct = dict(
            actions.get("direct_python") if isinstance(actions.get("direct_python"), dict) else {}
        )
        direct["module"] = _facade().sanitize_employee_stem(pack_id_hint or pid)
        direct.setdefault("action", "convert")
        if rule_spec.get("default_output_relpath"):
            direct.setdefault("default_output_relpath", rule_spec["default_output_relpath"])
        if rule_spec.get("template_relpath"):
            direct.setdefault("default_template_relpath", rule_spec["template_relpath"])
        actions["handlers"] = ["direct_python"]
        actions["direct_python"] = direct
    merged_v2["actions"] = actions
    if rule_spec.get("accepted_extensions"):
        perception = (
            merged_v2.get("perception") if isinstance(merged_v2.get("perception"), dict) else {}
        )
        perception["accepted_extensions"] = rule_spec["accepted_extensions"]
        merged_v2["perception"] = perception
    ident = dict(merged_v2.get("identity") if isinstance(merged_v2.get("identity"), dict) else {})
    ident.update(
        {
            "id": pid,
            "version": str(out.get("version") or "1.0.0"),
            "artifact": "employee_pack",
            "name": str(out.get("name") or pid),
        }
    )
    raw_desc = str(ident.get("description") or out.get("description") or brief).strip()
    if _facade().re.match("^(你是[一]?(名|位|个)|角色[：:])", raw_desc):
        emp_name = str(out.get("name") or pid)
        raw_desc = f"{emp_name}。{_facade()._clean_brief_for_description(_facade().re.sub('^(你是[一]?(名|位|个)|角色[：:])', '', raw_desc), 200)}"
    ident["description"] = _facade()._clean_brief_for_description(raw_desc, 500)
    merged_v2["identity"] = ident
    out["description"] = _facade()._clean_brief_for_description(
        str(out.get("description") or brief), 400
    )
    top_desc = str(out.get("description") or "")
    if _facade().re.match("^(你是[一]?(名|位|个)|角色[：:])", top_desc):
        out["description"] = (
            f"{out.get('name') or pid}。{_facade()._clean_brief_for_description(_facade().re.sub('^(你是[一]?(名|位|个)|角色[：:])', '', top_desc), 200)}"
        )
    cog = merged_v2.get("cognition") if isinstance(merged_v2.get("cognition"), dict) else {}
    agent_cfg = cog.get("agent") if isinstance(cog.get("agent"), dict) else {}
    sp = str(agent_cfg.get("system_prompt") or "")
    if "llm_md" in sp or "echo" in sp or "调用 LLM" in sp:
        agent_cfg["system_prompt"] = fallback["employee_config_v2"]["cognition"]["agent"][
            "system_prompt"
        ]
        cog["agent"] = agent_cfg
        merged_v2["cognition"] = cog
    fb_few = (
        fallback.get("employee_config_v2", {})
        .get("cognition", {})
        .get("agent", {})
        .get("few_shot_examples")
        or []
    )
    cur_few = agent_cfg.get("few_shot_examples") or []
    if not cur_few and fb_few:
        agent_cfg["few_shot_examples"] = fb_few
        cog["agent"] = agent_cfg
        merged_v2["cognition"] = cog
    out["employee_config_v2"] = merged_v2
    out["actions"] = dict(actions)
    bundles = out.get("workflow_bundles")
    if isinstance(bundles, list):
        for b in bundles:
            if not isinstance(b, dict):
                continue
            raw_desc = str(b.get("description") or "")
            cleaned = _facade()._clean_brief_for_description(raw_desc, 500)
            if not cleaned:
                cleaned = str(b.get("name") or "")
            b["description"] = cleaned
    return out


def _sanitize_workflow_bundles(manifest: _facade().Dict[str, _facade().Any]) -> None:
    """Clean bundle names/descriptions polluted by NL graph or voice planning."""
    name = str(manifest.get("name") or manifest.get("id") or "工作流").strip()
    bundles = manifest.get("workflow_bundles")
    if not isinstance(bundles, list):
        return
    for b in bundles:
        if not isinstance(b, dict):
            continue
        raw_name = str(b.get("name") or "").strip()
        if (
            not raw_name
            or raw_name in ("（无回复）", "(无回复)")
            or _facade()._PLACEHOLDER_BRIEF.search(raw_name)
        ):
            b["name"] = name
        raw_desc = str(b.get("description") or "")
        cleaned = _facade()._clean_brief_for_description(raw_desc, 500)
        b["description"] = cleaned or name
