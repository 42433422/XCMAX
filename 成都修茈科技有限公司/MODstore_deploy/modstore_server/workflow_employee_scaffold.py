"""从工作台为 Mod 追加 workflow_employees 条目并生成可选 FastAPI 占位路由（骨架 Mod）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from modman.manifest_util import read_manifest, save_manifest_validated
from modstore_server.file_safe import write_text_file


def _write_stub(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_file(path, content)


class WorkflowEmployeeScaffoldDTO(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=256)
    panel_title: str = Field("", max_length=256)
    panel_summary: str = Field("", max_length=8000)
    template: str = Field("skeleton_router", pattern="^(skeleton_router)$")
    force_auto_merge: bool = False


_EMP_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def _sanitize_py_module(emp_id: str) -> str:
    s = re.sub(r"[^a-z0-9_]", "_", (emp_id or "").strip().lower())
    if s and s[0].isdigit():
        s = "e_" + s
    return s or "emp"


def _blueprints_path(mod_dir: Path, manifest: Dict[str, Any]) -> Path:
    be = manifest.get("backend") if isinstance(manifest.get("backend"), dict) else {}
    entry = str(be.get("entry") or "blueprints").strip() or "blueprints"
    stem = entry.replace(".py", "", 1).replace(".PY", "")
    return mod_dir / "backend" / f"{stem}.py"


def _blueprints_is_skeleton_mergeable(text: str) -> bool:
    if "def register_fastapi_routes" not in text:
        return False
    if text.count("APIRouter(") != 1:
        return False
    if "importlib" in text or "exec_module" in text or "spec_from_file_location" in text:
        return False
    if text.count("app.include_router(router)") != 1:
        return False
    return True


def _stub_module_body(emp_id: str, safe_mod: str) -> str:
    # 生成源码字符串（不用外层 f-string，避免引号/大括号转义出错）
    return (
        f'"""Auto-generated stub for workflow employee `{emp_id}` (MODstore scaffold)."""\n\n'
        "from __future__ import annotations\n\n"
        "import logging\n\n"
        "from fastapi import APIRouter\n\n"
        "logger = logging.getLogger(__name__)\n\n\n"
        "def mount_employee_router(app, mod_id: str) -> None:\n"
        '    """在宿主 ``register_fastapi_routes`` 中挂载本员工占位 API。"""\n'
        f'    prefix = f"/api/mod/{{mod_id}}/emp/{emp_id}"\n'
        f'    r = APIRouter(prefix=prefix, tags=[f"mod-{{mod_id}}-emp-{emp_id}"])\n\n'
        '    @r.get("/status")\n'
        "    async def _status():\n"
        "        return {\n"
        '            "ok": True,\n'
        f'            "employee_id": "{emp_id}",\n'
        '            "mod_id": mod_id,\n'
        '            "message": "占位路由：请在此文件实现真实业务逻辑。",\n'
        "        }\n\n"
        "    app.include_router(r)\n"
        f'    logger.info("Mounted employee stub router: %s emp={emp_id}", mod_id)\n'
    )


def _ensure_employee_stubs_pkg(mod_dir: Path) -> Path:
    pkg = mod_dir / "backend" / "employee_stubs"
    pkg.mkdir(parents=True, exist_ok=True)
    init_py = pkg / "__init__.py"
    if not init_py.is_file():
        init_py.write_text('"""Generated employee route stubs."""\n', encoding="utf-8")
    return pkg


def _merge_blueprints(blueprints_text: str, safe_mod: str, emp_id: str) -> str:
    needle = "app.include_router(router)"
    idx = blueprints_text.find(needle)
    if idx < 0:
        raise ValueError("未找到 app.include_router(router)，无法自动合并")
    line_end = blueprints_text.find("\n", idx)
    if line_end < 0:
        line_end = len(blueprints_text)
    insert_at = line_end + 1
    indent_match = re.search(r"^(\s*)" + re.escape(needle), blueprints_text, re.MULTILINE)
    indent = indent_match.group(1) if indent_match else "    "
    block = (
        f"{indent}try:\n"
        f"{indent}    from .employee_stubs import {safe_mod} as _emp_stub_{safe_mod}\n"
        f"{indent}    _emp_stub_{safe_mod}.mount_employee_router(app, mod_id)\n"
        f"{indent}except Exception:\n"
        f'{indent}    logger.exception("挂载员工占位路由失败 emp=%s", "{emp_id}")\n'
    )
    return blueprints_text[:insert_at] + block + blueprints_text[insert_at:]


def run_workflow_employee_scaffold(
    mod_dir: Path,
    body: WorkflowEmployeeScaffoldDTO,
    *,
    allow_blueprint_merge: bool,
) -> Dict[str, Any]:
    emp_id = body.id.strip()
    if not _EMP_ID_RE.match(emp_id):
        raise ValueError(
            "员工 id 须为小写字母开头，仅含小写字母、数字、下划线、连字符（1–64 字符）"
        )
    data, err = read_manifest(mod_dir)
    if err or not data:
        raise ValueError(err or "manifest 无效")
    manifest = dict(data)
    wf = manifest.get("workflow_employees")
    if wf is None:
        wf = []
    if not isinstance(wf, list):
        raise ValueError("manifest.workflow_employees 须为数组")
    for it in wf:
        if isinstance(it, dict) and str(it.get("id") or "").strip() == emp_id:
            raise ValueError(f"workflow_employees 已存在 id={emp_id!r}")

    safe_mod = "e_" + _sanitize_py_module(emp_id)
    if not safe_mod.replace("e_", ""):
        raise ValueError("无效的员工 id")

    files_written: List[str] = []
    merge_hint = ""
    merged_blueprint = False

    stub_pkg = _ensure_employee_stubs_pkg(mod_dir)
    stub_path = stub_pkg / f"{safe_mod}.py"
    if stub_path.is_file():
        raise ValueError(
            f"占位文件已存在: backend/employee_stubs/{safe_mod}.py（请换 id 或手动删除）"
        )
    _write_stub(stub_path, _stub_module_body(emp_id, safe_mod))
    files_written.append(f"backend/employee_stubs/{safe_mod}.py")

    bp_path = _blueprints_path(mod_dir, manifest)
    if bp_path.is_file():
        bp_text = bp_path.read_text(encoding="utf-8")
        already_mounted = (
            f"_emp_stub_{safe_mod}" in bp_text or f"employee_stubs.{safe_mod}" in bp_text
        )
        can_merge = False if already_mounted else _blueprints_is_skeleton_mergeable(bp_text)
        if already_mounted:
            merge_hint = "blueprints 中似乎已包含该员工的挂载代码，已跳过自动合并。"
        elif can_merge and (allow_blueprint_merge or body.force_auto_merge):
            try:
                new_bp = _merge_blueprints(bp_text, safe_mod, emp_id)
                write_text_file(bp_path, new_bp)
                files_written.append(str(bp_path.relative_to(mod_dir)).replace("\\", "/"))
                merged_blueprint = True
            except Exception as e:
                merge_hint = f"已生成占位文件，但自动合并 blueprints 失败：{e}。请手动在 register_fastapi_routes 内调用 mount_employee_router。"
        elif not can_merge:
            merge_hint = (
                "未自动修改 blueprints.py（检测到非骨架模板或含动态 import）。\n"
                "请在 `register_fastapi_routes` 内、`app.include_router(router)` 之后加入：\n"
                f"    from .employee_stubs import {safe_mod} as _emp_stub_{safe_mod}\n"
                f"    _emp_stub_{safe_mod}.mount_employee_router(app, mod_id)\n"
            )
        elif can_merge and not allow_blueprint_merge and not body.force_auto_merge:
            merge_hint = (
                "当前为可合并骨架，但未开启自动合并。可传 force_auto_merge=true 重试，或手动加入：\n"
                f"    from .employee_stubs import {safe_mod} as _emp_stub_{safe_mod}\n"
                f"    _emp_stub_{safe_mod}.mount_employee_router(app, mod_id)\n"
            )
    else:
        merge_hint = f"未找到 {bp_path.name}，请自行在入口中挂载 employee_stubs.{safe_mod}.mount_employee_router。"

    entry: Dict[str, Any] = {
        "id": emp_id,
        "label": body.label.strip(),
        "panel_title": (body.panel_title or "").strip(),
        "panel_summary": (body.panel_summary or "").strip(),
    }
    wf = list(wf)
    wf.append(entry)
    manifest["workflow_employees"] = wf
    warnings = save_manifest_validated(mod_dir, manifest)
    return {
        "ok": True,
        "files_written": files_written,
        "manifest_warnings": warnings,
        "merged_blueprint": merged_blueprint,
        "merge_hint": merge_hint or None,
        "employee_stub_module": safe_mod,
    }


def scaffold_auto_merge_default() -> bool:
    """是否默认允许骨架 blueprints 自动合并（可用环境变量关闭）。"""
    import os

    raw = (os.environ.get("MODSTORE_SCAFFOLD_AUTO_MERGE_BLUEPRINTS") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


# 微信 + 电话业务员工作流模板（供前端或工具预填 nodes/edges）
PHONE_WECHAT_SCAFFOLD: Dict[str, Any] = {
    "name": "微信电话业务员",
    "description": "客户消息/来电 → 意图识别 → 分支处理 → 通知或人工",
    "nodes": [
        {
            "id": "start",
            "type": "trigger",
            "label": "客户消息",
            "config": {"trigger_type": "webhook"},
        },
        {
            "id": "intent",
            "type": "employee",
            "label": "意图识别",
            "config": {"task": "识别客户意图"},
        },
        {
            "id": "answer",
            "type": "employee",
            "label": "智能回答",
            "config": {"task": "回答客户问题"},
        },
        {
            "id": "escalate",
            "type": "action",
            "label": "转人工",
            "config": {"handler": "wechat_notify"},
        },
    ],
    "edges": [
        {"source": "start", "target": "intent"},
        {"source": "intent", "target": "answer"},
        {"source": "intent", "target": "escalate"},
    ],
}
