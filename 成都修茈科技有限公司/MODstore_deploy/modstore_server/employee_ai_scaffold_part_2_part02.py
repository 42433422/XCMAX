# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_ai_scaffold")


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
