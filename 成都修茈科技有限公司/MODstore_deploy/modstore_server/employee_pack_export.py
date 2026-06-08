"""从已入库 Mod + workflow_employees 条目生成 employee_pack manifest 与最小 zip。

manifest 会带上 ``employee_config_v2``，让运行时（``execute_employee_task``）
能走声明式 perception/cognition/actions，即使没有独立 Python 脚本也能响应。
若 Mod 目录里已有 ``backend/employees/<stem>.py``，会把该源码一起塞进 zip
``<pack_id>/source/employee.py`` 方便下载查看（不作为运行时入口）。
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modman.manifest_util import validate_manifest_dict
from modstore_server.employee_ai_scaffold import (
    _default_employee_config_v2,
    build_employee_pack_zip,
)
from modstore_server.employee_pack_blueprints_template import (
    render_employee_pack_blueprints_py,
    render_employee_pack_employee_py,
)
from modstore_server.employee_pack_standalone_template import (
    render_standalone_cli_py,
    render_standalone_handler_llm_md_py,
    render_standalone_handler_no_llm_py,
    render_standalone_llm_adapter_py,
    render_standalone_main_py,
    render_standalone_readme_md,
    render_standalone_runner_py,
    standalone_import_prefix,
)
from modstore_server.mod_ai_scaffold import normalize_mod_id
from modstore_server.mod_employee_impl_scaffold import sanitize_employee_stem


def _sanitize_employee_stem(emp_id: str) -> str:
    s = re.sub(r"[^a-z0-9_]", "_", (emp_id or "").strip().lower())
    if s and s[0].isdigit():
        s = "e_" + s
    return s or "emp"


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _slug_id(raw: str, fallback: str) -> str:
    x = (raw or "").strip().lower()
    x = re.sub(r"[^a-z0-9._-]+", "-", x)
    x = re.sub(r"-{2,}", "-", x).strip("-")
    if not x:
        x = fallback
    if x and not x[0].isalnum():
        x = "x" + x
    if not _ID_RE.match(x):
        x = fallback
    return x[:48]


def build_employee_pack_manifest_from_workflow(
    mod_id: str,
    mod_manifest: Dict[str, Any],
    wf_entry: Dict[str, Any],
    *,
    workflow_index: int = 0,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    用 Mod 的 manifest 与单条 workflow_employee 构造可校验的 employee_pack manifest。
    pack id 优先 {mod_id}-{wf_id}，避免与库内其他包 id 冲突。
    """
    mid = normalize_mod_id(mod_id)
    if not mid:
        return None, "Mod id 无效"

    wf = wf_entry if isinstance(wf_entry, dict) else {}
    wf_raw_id = str(wf.get("id") or "").strip()
    wf_slug = normalize_mod_id(wf_raw_id) or _slug_id(wf_raw_id, f"emp{workflow_index}")
    pack_id = f"{mid}-{wf_slug}" if wf_slug != mid else mid
    if len(pack_id) > 48:
        pack_id = pack_id[:48]
    if not _ID_RE.match(pack_id):
        pack_id = mid

    name_src = str(
        wf.get("label") or wf.get("panel_title") or mod_manifest.get("name") or pack_id
    ).strip()
    name = name_src[:200] or pack_id
    ver = str(mod_manifest.get("version") or "1.0.0").strip() or "1.0.0"
    desc = str(
        wf.get("panel_summary") or wf.get("description") or mod_manifest.get("description") or ""
    ).strip()[:4000]

    emp_id = pack_id
    label = str(wf.get("label") or name).strip() or emp_id
    caps_in = wf.get("capabilities")
    caps: List[str] = []
    if isinstance(caps_in, list):
        for x in caps_in:
            if isinstance(x, str) and x.strip():
                caps.append(x.strip()[:128])

    manifest: Dict[str, Any] = {
        "id": pack_id,
        "name": name,
        "version": ver,
        "author": str(mod_manifest.get("author") or "").strip(),
        "description": desc,
        "artifact": "employee_pack",
        "scope": "global",
        "dependencies": (
            mod_manifest["dependencies"]
            if isinstance(mod_manifest.get("dependencies"), dict)
            else {"xcagi": ">=1.0.0"}
        ),
        "employee": {
            "id": emp_id,
            "label": label[:200],
            "capabilities": caps,
        },
    }
    manifest["employee_config_v2"] = _default_employee_config_v2(
        pid=pack_id,
        name=name,
        description=desc,
        employee_id=emp_id,
        label=label,
        capabilities=caps,
    )
    from modstore_server.xcagi_host_profile import merge_workflow_employee_for_manifest

    manifest["workflow_employees"] = [
        merge_workflow_employee_for_manifest(
            employee_id=emp_id,
            label=label,
            panel_summary=desc,
            host_profile=None,
        )
    ]
    manifest["backend"] = {"entry": "blueprints", "init": "mod_init"}
    _ensure_v2_handlers_consistent(manifest, emp_id)
    ve = validate_manifest_dict(manifest)
    if ve:
        return None, "manifest 校验: " + "; ".join(ve)
    return manifest, ""


def _ensure_v2_handlers_consistent(manifest: Dict[str, Any], emp_id: str) -> None:
    top_actions = manifest.get("actions") if isinstance(manifest.get("actions"), dict) else {}
    top_handlers = (
        top_actions.get("handlers") if isinstance(top_actions.get("handlers"), list) else []
    )
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    v2_actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {}
    v2_handlers = v2_actions.get("handlers") if isinstance(v2_actions.get("handlers"), list) else []
    if top_handlers and v2_handlers != top_handlers:
        v2_actions["handlers"] = list(top_handlers)
    if "direct_python" in (v2_actions.get("handlers") or []):
        direct = (
            v2_actions.get("direct_python")
            if isinstance(v2_actions.get("direct_python"), dict)
            else {}
        )
        direct.setdefault("module", sanitize_employee_stem(emp_id))
        direct.setdefault("action", "convert")
        direct.setdefault("default_output_relpath", "outputs/employee_output.xlsx")
        direct.setdefault("default_template_relpath", "")
        direct.setdefault("default_use_personnel_roster", True)
        v2_actions["direct_python"] = direct
    v2["actions"] = v2_actions
    perception = v2.get("perception") if isinstance(v2.get("perception"), dict) else {}
    if perception.get("type") not in ("file_or_text", "file"):
        perception["type"] = "file_or_text"
    v2["perception"] = perception
    cog = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
    agent_cfg = cog.get("agent") if isinstance(cog.get("agent"), dict) else {}
    few = agent_cfg.get("few_shot_examples")
    if not few:
        emp_name = str(v2.get("identity", {}).get("name") or manifest.get("name") or emp_id)
        if "审核" in emp_name or "合同" in emp_name:
            agent_cfg["few_shot_examples"] = [
                {
                    "input": "上传一份AI技术服务合同",
                    "output": "审核报告：1) 第3条服务范围表述模糊，建议明确具体服务项；2) 缺少数据安全条款，建议补充；3) 违约责任条款不完整，建议增加违约金比例。",
                },
            ]
        cog["agent"] = agent_cfg
        v2["cognition"] = cog
    manifest["employee_config_v2"] = v2


def _read_employee_source(mod_dir: Optional[Path], emp_id: str) -> Optional[str]:
    if not mod_dir:
        return None
    try:
        stem = _sanitize_employee_stem(emp_id)
        p = mod_dir / "backend" / "employees" / f"{stem}.py"
        if p.is_file():
            return p.read_text(encoding="utf-8")
    except OSError:
        return None
    return None


def _render_employee_py_for_manifest(
    manifest: Dict[str, Any],
    employee_id: str,
    stem: str,
    label: str,
) -> str:
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {}
    handlers = actions.get("handlers") if isinstance(actions.get("handlers"), list) else []
    if "direct_python" in handlers:
        from modstore_server.employee_asset_pipeline import render_direct_python_asset_worker

        runtime_mod = re.sub(r"[^a-z0-9_]+", "_", employee_id.lower()).strip("_")
        if runtime_mod.endswith("_employee"):
            runtime_mod = runtime_mod[: -len("_employee")] or runtime_mod
        rule_spec = {}
        direct_cfg = (
            actions.get("direct_python") if isinstance(actions.get("direct_python"), dict) else {}
        )
        if direct_cfg:
            rule_spec["default_output_relpath"] = direct_cfg.get(
                "default_output_relpath", "outputs/employee_output.xlsx"
            )
            rule_spec["default_template_relpath"] = direct_cfg.get("default_template_relpath", "")
        return render_direct_python_asset_worker(
            employee_id=employee_id,
            label=label,
            runtime_module=runtime_mod,
            rule_spec=rule_spec,
        )
    return render_employee_pack_employee_py(employee_id=employee_id, stem=stem, label=label)


def collect_vendor_modules_from_pack(pack_dir: Path) -> Optional[Dict[str, str]]:
    """Collect vendor/*.py keyed for zip (relative to runtime module dir, e.g. convert.py)."""
    vendor_dir = pack_dir / "backend" / "vendor"
    if not vendor_dir.is_dir():
        return None
    out: Dict[str, str] = {}
    for vp in sorted(vendor_dir.rglob("*.py")):
        if vp.name == "__init__.py":
            continue
        vrel = vp.relative_to(vendor_dir)
        parts = vrel.parts
        if len(parts) >= 2:
            key = "/".join(parts[1:])
        elif len(parts) == 1:
            key = parts[0]
        else:
            continue
        try:
            out[key] = vp.read_text(encoding="utf-8")
        except OSError:
            pass
    return out if out else None


def _build_employee_pack_zip_with_source(
    pack_id: str,
    manifest: Dict[str, Any],
    source_py: Optional[str],
    vendor_modules: Optional[Dict[str, str]] = None,
) -> bytes:
    import copy

    mf = copy.deepcopy(manifest)
    mf["id"] = pack_id
    if isinstance(mf.get("employee"), dict):
        mf["employee"]["id"] = pack_id
    for _row in mf.get("workflow_employees") or []:
        if isinstance(_row, dict):
            _row["id"] = pack_id
    buf = io.BytesIO()
    body = json.dumps(mf, ensure_ascii=False, indent=2) + "\n"
    emp = mf.get("employee") if isinstance(mf.get("employee"), dict) else {}
    eid = pack_id
    stem = sanitize_employee_stem(eid)
    label = str(emp.get("label") or eid).strip()
    zip_standalone_prefix = standalone_import_prefix(pack_id)
    bp = render_employee_pack_blueprints_py(
        pack_id=pack_id, employee_id=eid, stem=stem, label=label
    )
    rendered_py = _render_employee_py_for_manifest(manifest, eid, stem, label)
    use_source = source_py and source_py.strip()
    if use_source:
        v2_check = (
            manifest.get("employee_config_v2")
            if isinstance(manifest.get("employee_config_v2"), dict)
            else {}
        )
        act_check = v2_check.get("actions") if isinstance(v2_check.get("actions"), dict) else {}
        h_check = act_check.get("handlers") if isinstance(act_check.get("handlers"), list) else []
        if "direct_python" in h_check and "_DISPATCH" in source_py:
            use_source = None
    emp_py = (source_py.strip() + "\n") if use_source else rendered_py
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {}
    handlers = actions.get("handlers") if isinstance(actions.get("handlers"), list) else []
    is_direct_python = "direct_python" in handlers
    runtime_mod_name = re.sub(r"[^a-z0-9_]+", "_", eid.lower()).strip("_")
    if runtime_mod_name.endswith("_employee"):
        runtime_mod_name = runtime_mod_name[: -len("_employee")] or runtime_mod_name
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # ── 平台原有文件（不变）─────────────────────────────────────────────
        zf.writestr(f"{pack_id}/manifest.json", body)
        zf.writestr(f"{pack_id}/backend/blueprints.py", bp)
        zf.writestr(f"{pack_id}/backend/employees/{stem}.py", emp_py)
        zf.writestr(
            f"{pack_id}/backend/employees/__init__.py",
            '"""Generated employee implementations (employee_pack)."""\n',
        )
        # ── vendor 运行时模块（direct_python 员工必需）───────────────────────
        if is_direct_python and vendor_modules:
            for mod_name, mod_src in vendor_modules.items():
                zf.writestr(f"{pack_id}/backend/vendor/{runtime_mod_name}/{mod_name}", mod_src)
        elif is_direct_python:
            from modstore_server.employee_asset_pipeline import (
                _fallback_convert_module,
                render_runtime_modules,
            )

            direct_cfg = (
                actions.get("direct_python")
                if isinstance(actions.get("direct_python"), dict)
                else {}
            )
            rule_spec = {
                "brief": str(manifest.get("description") or ""),
                "default_output_relpath": direct_cfg.get(
                    "default_output_relpath", "outputs/employee_output.xlsx"
                ),
                "default_template_relpath": direct_cfg.get("default_template_relpath", ""),
            }
            runtime_modules = render_runtime_modules(rule_spec)
            for mod_name, mod_src in runtime_modules.items():
                zf.writestr(f"{pack_id}/backend/vendor/{runtime_mod_name}/{mod_name}", mod_src)
        if source_py:
            zf.writestr(f"{pack_id}/source/employee.py", source_py)
            zf.writestr(
                f"{pack_id}/source/README.md",
                "# 员工源码\n\n本文件仅为查看参考。宿主通过 `backend/employees/<stem>.py` 执行。\n",
            )
        # ── zipapp 独立可执行入口（新增，对平台透明）──────────────────────
        zf.writestr("__main__.py", render_standalone_main_py(pack_id))
        zf.writestr(f"{zip_standalone_prefix}/__init__.py", "")
        zf.writestr(f"{zip_standalone_prefix}/standalone/__init__.py", "")
        zf.writestr(
            f"{zip_standalone_prefix}/standalone/cli.py",
            render_standalone_cli_py(pack_id, eid, zip_standalone_prefix),
        )
        zf.writestr(
            f"{zip_standalone_prefix}/standalone/runner.py",
            render_standalone_runner_py(pack_id, zip_standalone_prefix),
        )
        zf.writestr(
            f"{zip_standalone_prefix}/standalone/llm_adapter.py", render_standalone_llm_adapter_py()
        )
        zf.writestr(f"{zip_standalone_prefix}/standalone/handlers/__init__.py", "")
        zf.writestr(
            f"{zip_standalone_prefix}/standalone/handlers/no_llm.py",
            render_standalone_handler_no_llm_py(),
        )
        zf.writestr(
            f"{zip_standalone_prefix}/standalone/handlers/llm_md.py",
            render_standalone_handler_llm_md_py(),
        )
        zf.writestr(
            f"{zip_standalone_prefix}/standalone/fixtures/example_input.json",
            '{"task": "validate"}\n',
        )
        zf.writestr(f"{zip_standalone_prefix}/standalone/requirements.txt", "")
        zf.writestr(
            f"{zip_standalone_prefix}/standalone/README.md",
            render_standalone_readme_md(pack_id, label),
        )
    return buf.getvalue()


def build_employee_pack_zip_from_workflow(
    mod_id: str,
    mod_manifest: Dict[str, Any],
    wf_entry: Dict[str, Any],
    *,
    workflow_index: int = 0,
    mod_dir: Optional[Path] = None,
) -> Tuple[Optional[bytes], str, Optional[str]]:
    """返回 zip 字节、错误信息、选用的 pack_id。

    若传入 ``mod_dir``，会尝试读取 Mod 目录下的员工 Python 源码写入 zip 方便查看；
    运行时入口仍是 Mod 自己的 FastAPI 路由。
    """
    manifest, err = build_employee_pack_manifest_from_workflow(
        mod_id, mod_manifest, wf_entry, workflow_index=workflow_index
    )
    if err or not manifest:
        return None, err or "无法生成 manifest", None
    pid = str(manifest.get("id") or "").strip()
    emp_id = pid
    src = _read_employee_source(mod_dir, emp_id) if mod_dir else None
    if src:
        raw = _build_employee_pack_zip_with_source(pid, manifest, src)
    else:
        raw = build_employee_pack_zip(pid, manifest)
    return raw, "", pid
