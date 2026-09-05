"""Preserve an employee source while delivering it as an owner-bound RuntimeMod."""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path
from typing import Any

_PANEL = r"""export function mount(root, sdk) {
  const node = (tag, text = '') => { const el = document.createElement(tag); el.textContent = text; return el }
  const page = node('section'); page.style.cssText = 'max-width:800px;margin:auto;display:grid;gap:16px'
  const title = node('h1', '专属 AI 员工')
  const task = node('textarea'); task.placeholder = '请说明员工本次需要完成的工作'; task.rows = 5
  const file = node('input'); file.type = 'file'; file.setAttribute('aria-label', '员工输入文件')
  const run = node('button', '执行员工任务'); run.type = 'button'
  const status = node('p'); status.setAttribute('role', 'status')
  const output = node('pre'); output.style.whiteSpace = 'pre-wrap'
  const links = node('div')
  page.append(title, task, file, run, status, output, links); root.append(page)
  const request = async (path, init) => {
    const response = await sdk.request(path, init); const body = await response.json()
    if (!response.ok || body.success !== true) throw new Error(typeof body.detail === 'string' ? body.detail : body.data?.error || body.error || '员工执行失败')
    return body
  }
  run.addEventListener('click', async () => {
    run.disabled = true; status.textContent = '员工正在处理…'; output.textContent = ''; links.replaceChildren()
    try {
      const payload = { user_request: task.value, task: task.value }
      if (file.files?.[0]) {
        const form = new FormData(); form.append('file', file.files[0])
        payload.file_path = (await request('/employee/input', {method:'POST', body:form})).file_path
      }
      const body = await request('/employee/run', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)})
      output.textContent = body.data.summary || JSON.stringify(body.data, null, 2)
      status.textContent = '员工任务已完成'
      for (const path of body.files || []) {
        const link = node('a', `下载 ${path}`); link.href = `/api/mod/${sdk.modId}/employee/files?path=${encodeURIComponent(path)}`; link.download = ''; links.append(link)
      }
    } catch (error) { status.textContent = error.message || '员工执行失败，请重试' }
    finally { run.disabled = false }
  }, {signal:sdk.signal})
  return () => page.remove()
}
"""


def _exports(path: Path, name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
        or isinstance(node, ast.ImportFrom)
        and any((alias.asname or alias.name) == name for alias in node.names)
        for node in tree.body
    )


def wrap_private_employee(source: Path, destination: Path) -> Path:
    original: dict[str, Any] = json.loads((source / "manifest.json").read_text())
    if original.get("artifact") != "employee_pack":
        raise ValueError("员工封装源必须是真实 employee_pack")
    employee_id = str((original.get("employee") or {}).get("id") or "")
    probe = original.get("delivery_verification") or {}
    entry = str((original.get("backend") or {}).get("entry") or "")
    if not employee_id or probe.get("handler") != "verify_delivery" or not probe.get("case_id"):
        raise ValueError("原员工缺少身份或真实业务探针，须在原工单补齐能力")
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", entry):
        raise ValueError("原员工业务探针入口无效")
    probe_stem = entry.replace(".", "/")
    probe_path = source / "backend" / (probe_stem + ".py")
    if not probe_path.is_file():
        probe_stem += "/__init__"
        probe_path = source / "backend" / (probe_stem + ".py")
    if not probe_path.is_file() or not _exports(probe_path, "verify_delivery"):
        raise ValueError("原员工未实现实际业务 verify_delivery，不能以注册或健康状态交付")
    actions = (original.get("employee_config_v2") or {}).get("actions") or {}
    requested = str((actions.get("direct_python") or {}).get("module") or "")
    workers = [
        path for path in (source / "backend/employees").glob("*.py") if _exports(path, "run")
    ]
    worker = next((path for path in workers if path.stem == requested), None)
    if worker is None and len(workers) == 1:
        worker = workers[0]
    if worker is None:
        raise ValueError("原员工须提供唯一明确的 run(payload, ctx) 入口，不能依赖全局 registry")
    shutil.copytree(source, destination)
    manifest = dict(original)
    mid = str(manifest["id"])
    manifest.update(
        artifact="mod",
        scope="account",
        source_employee={
            "pack_id": mid,
            "employee_id": employee_id,
            "version": original["version"],
        },
        private_employee_runtime={
            "sdk_version": 1,
            "employee_id": employee_id,
            "run_module": f"employees/{worker.stem}",
            "probe_module": probe_stem,
        },
        backend={"entry": "delivery_employee"},
        frontend={
            "runtime": {
                "sdk_version": 1,
                "source": "frontend/src/delivery-employee.js",
                "entry": "frontend/runtime/delivery-employee.js",
                "routes": [
                    {"path": f"/mod/{mid}/employee", "title": original.get("name", employee_id)}
                ],
            }
        },
        workflow_employees=[],
        menu=[
            {
                "id": "private-employee",
                "label": original.get("name", employee_id),
                "path": f"/mod/{mid}/employee",
                "icon": "robot",
            }
        ],
    )
    (destination / "source-employee-manifest.json").write_text(
        json.dumps(original, ensure_ascii=False, indent=2)
    )
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    (destination / "backend/delivery_employee.py").write_text(
        "from app.mod_sdk.private_employee_runtime import register_private_employee_routes, verify_employee_delivery\n"
        f"MOD_ID = {mid!r}\n"
        "def register_fastapi_routes(app, mod_id):\n    register_private_employee_routes(app, mod_id)\n"
        "async def verify_delivery(request):\n    return await verify_employee_delivery(request, MOD_ID)\n"
    )
    (destination / "frontend/src").mkdir(parents=True, exist_ok=True)
    (destination / "frontend/src/delivery-employee.js").write_text(_PANEL)
    return destination
