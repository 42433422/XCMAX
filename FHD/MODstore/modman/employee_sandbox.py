"""工作流员工沙箱：静态结构校验 + 可选 HTTP 探测（依赖最少，供 MODstore / CLI 共用）。"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from modman.artifact_constants import ARTIFACT_MOD, normalize_artifact
from modman.manifest_util import read_manifest, validate_manifest_dict

_EMP_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def _sanitize_py_module(emp_id: str) -> str:
    s = re.sub(r"[^a-z0-9_]", "_", (emp_id or "").strip().lower())
    if s and s[0].isdigit():
        s = "e_" + s
    return s or "emp"


def employee_stub_stem(emp_id: str) -> str:
    """与 workflow_employee_scaffold 生成的 backend/employee_stubs/<stem>.py 文件名一致。"""
    emp_id = (emp_id or "").strip()
    if not _EMP_ID_RE.match(emp_id):
        raise ValueError(f"员工 id 非法: {emp_id!r}")
    base = _sanitize_py_module(emp_id)
    stem = "e_" + base
    if not stem.replace("e_", ""):
        raise ValueError("无效的员工 id")
    return stem


def mod_backend_entry_py_path(mod_dir: Path, manifest: Dict[str, Any]) -> Path:
    be = manifest.get("backend") if isinstance(manifest.get("backend"), dict) else {}
    entry = str(be.get("entry") or "blueprints").strip() or "blueprints"
    stem = entry.replace(".py", "", 1).replace(".PY", "")
    return mod_dir / "backend" / f"{stem}.py"


def extract_mod_root_from_zip(zip_path: Path, work_dir: Path) -> Path:
    """解压 zip 并返回含 manifest.json 的 Mod 根目录（支持根级 manifest 或单顶层目录）。"""
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if n.strip() and not n.endswith("/")]
        if not names:
            raise ValueError("空 zip")
        if "manifest.json" in zf.namelist():
            zf.extractall(work_dir)
            return work_dir
        tops = {n.split("/")[0].strip() for n in names if "/" in n}
        if len(tops) != 1:
            raise ValueError(
                "zip 顶层须为单一目录（例如 my-mod/manifest.json），或包含根级 manifest.json；实际顶层: "
                + ", ".join(sorted(tops)[:12])
            )
        root_name = next(iter(tops))
        zf.extractall(work_dir)
        out = work_dir / root_name
        if not (out / "manifest.json").is_file():
            raise ValueError(f"解压后缺少 manifest.json: {out}")
        return out


def catalog_require_employee_sandbox() -> bool:
    raw = (os.environ.get("MODSTORE_CATALOG_REQUIRE_EMPLOYEE_SANDBOX") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def catalog_sandbox_probe_http() -> bool:
    raw = (os.environ.get("MODSTORE_CATALOG_SANDBOX_HTTP") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def run_static_employee_sandbox(mod_dir: Path) -> Dict[str, Any]:
    """
    对 **library 中已解压的 Mod 目录** 做静态沙箱检查。
    - artifact 非 mod：跳过（ok + skipped）。
    - 无 workflow_employees：跳过。
    - 有员工：每条须合法 id/label；须存在 backend/employee_stubs/<stem>.py；后端入口源码须出现对应 stem（挂载）。
    """
    errors: List[str] = []
    warnings: List[str] = []
    checks: List[Dict[str, Any]] = []

    data, err = read_manifest(mod_dir)
    if err or not data:
        errors.append(err or "manifest 无效")
        return {"ok": False, "skipped": False, "errors": errors, "warnings": warnings, "checks": checks}

    checks.append({"name": "manifest_readable", "ok": True, "detail": str(mod_dir)})

    ve = validate_manifest_dict(data)
    for w in ve:
        errors.append(str(w))
    if ve:
        return {"ok": False, "skipped": False, "errors": errors, "warnings": warnings, "checks": checks}

    art = normalize_artifact(data)
    if art != ARTIFACT_MOD:
        return {
            "ok": True,
            "skipped": True,
            "reason": f"artifact={art}",
            "errors": [],
            "warnings": warnings,
            "checks": checks + [{"name": "artifact_skip", "ok": True, "detail": art}],
        }

    wf = data.get("workflow_employees")
    if not isinstance(wf, list) or len(wf) == 0:
        return {
            "ok": True,
            "skipped": True,
            "reason": "无 workflow_employees",
            "errors": [],
            "warnings": warnings,
            "checks": checks,
        }

    for idx, row in enumerate(wf):
        if not isinstance(row, dict):
            errors.append(f"workflow_employees[{idx}] 须为对象")
            continue
        emp_id = str(row.get("id") or "").strip()
        label = str(row.get("label") or "").strip()
        if not emp_id:
            errors.append(f"workflow_employees[{idx}] 缺少 id")
            continue
        if not _EMP_ID_RE.match(emp_id):
            errors.append(f"员工 id 非法: {emp_id!r}")
        if not label:
            errors.append(f"员工 {emp_id}: 缺少 label")
        try:
            stem = employee_stub_stem(emp_id)
        except ValueError as e:
            errors.append(str(e))
            continue
        stub = mod_dir / "backend" / "employee_stubs" / f"{stem}.py"
        if not stub.is_file():
            errors.append(f"员工 {emp_id}: 缺少占位模块 backend/employee_stubs/{stem}.py（请先在 MODstore 执行员工脚手架）")
        else:
            checks.append({"name": f"stub_file:{emp_id}", "ok": True, "detail": f"backend/employee_stubs/{stem}.py"})

    bp = mod_backend_entry_py_path(mod_dir, data)
    bp_text = ""
    if bp.is_file():
        bp_text = bp.read_text(encoding="utf-8", errors="ignore")
        checks.append({"name": "backend_entry_exists", "ok": True, "detail": bp.relative_to(mod_dir).as_posix()})
    else:
        warnings.append(f"未找到后端入口文件 {bp.relative_to(mod_dir).as_posix()}，无法校验挂载")

    if bp_text:
        for row in wf:
            if not isinstance(row, dict):
                continue
            emp_id = str(row.get("id") or "").strip()
            if not emp_id or not _EMP_ID_RE.match(emp_id):
                continue
            try:
                stem = employee_stub_stem(emp_id)
            except ValueError:
                continue
            stub = mod_dir / "backend" / "employee_stubs" / f"{stem}.py"
            if not stub.is_file():
                continue
            if stem not in bp_text:
                errors.append(
                    f"员工 {emp_id}: 后端入口未引用占位模块 {stem}（请在 register_fastapi_routes 内调用 mount_employee_router）"
                )
            else:
                checks.append({"name": f"stub_mount:{emp_id}", "ok": True, "detail": "entry 源码含 stub stem"})

    return {
        "ok": len(errors) == 0,
        "skipped": False,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


def run_http_employee_sandbox(mod_id: str, mod_dir: Path, manifest: Dict[str, Any], base_url: str) -> Dict[str, Any]:
    """对已在宿主注册的 Mod 探测 GET /api/mod/{mod_id}/emp/{emp_id}/status（可选，需 httpx + 可访问后端）。"""
    results: List[Dict[str, Any]] = []
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return {"ok": True, "skipped": True, "reason": "无 backend_base", "results": results}

    try:
        import httpx
    except ImportError:
        return {"ok": True, "skipped": True, "reason": "未安装 httpx", "results": results}

    wf = manifest.get("workflow_employees")
    if not isinstance(wf, list) or not wf:
        return {"ok": True, "skipped": True, "reason": "无员工", "results": results}

    all_ok = True
    with httpx.Client(timeout=8.0) as client:
        for row in wf:
            if not isinstance(row, dict):
                continue
            emp_id = str(row.get("id") or "").strip()
            if not emp_id:
                continue
            url = f"{base}/api/mod/{mod_id}/emp/{emp_id}/status"
            try:
                r = client.get(url)
                body: Any = None
                try:
                    body = r.json()
                except Exception:
                    body = None
                ok = r.status_code == 200 and isinstance(body, dict) and body.get("ok") is True
                results.append(
                    {"employee_id": emp_id, "url": url, "http_status": r.status_code, "ok": ok, "detail": str(body)[:300]}
                )
                if not ok:
                    all_ok = False
            except Exception as e:
                all_ok = False
                results.append({"employee_id": emp_id, "url": url, "http_status": None, "ok": False, "detail": str(e)})
    return {"ok": all_ok, "skipped": False, "results": results}


def run_employee_sandbox_on_zip(
    zip_path: Path,
    *,
    probe_http: bool = False,
    backend_base: Optional[str] = None,
) -> Dict[str, Any]:
    """解压 zip 到临时目录并运行静态 + 可选 HTTP 检查。"""
    zip_path = zip_path.resolve()
    if not zip_path.is_file():
        raise ValueError("zip 不存在")

    with tempfile.TemporaryDirectory(prefix="emp_sandbox_") as td:
        work = Path(td)
        mod_dir = extract_mod_root_from_zip(zip_path, work)
        data, err = read_manifest(mod_dir)
        if err or not data:
            return {
                "ok": False,
                "skipped": False,
                "errors": [err or "manifest 无效"],
                "warnings": [],
                "static": {},
                "http": {},
            }
        static = run_static_employee_sandbox(mod_dir)
        mid = str(data.get("id") or mod_dir.name).strip() or mod_dir.name
        http: Dict[str, Any] = {}
        if static.get("ok") and probe_http and backend_base and not static.get("skipped"):
            http = run_http_employee_sandbox(mid, mod_dir, data, backend_base)
        merge_errors = list(static.get("errors") or [])
        if static.get("ok") and http and not http.get("skipped") and not http.get("ok"):
            merge_errors.append("HTTP 探测未全部通过，见 http.results")
        ok = bool(static.get("ok")) and (not http or http.get("skipped") or http.get("ok", True))
        return {
            "ok": ok,
            "skipped": bool(static.get("skipped")),
            "errors": merge_errors,
            "warnings": list(static.get("warnings") or []),
            "static": static,
            "http": http,
            "mod_id": mid,
        }


def assert_employee_sandbox_passes_for_catalog_zip(
    zip_path: Path,
    *,
    probe_http: bool = False,
    backend_base: Optional[str] = None,
) -> None:
    """上架门禁：不通过则抛出 ValueError（文案供 HTTP 400）。"""
    res = run_employee_sandbox_on_zip(zip_path, probe_http=probe_http, backend_base=backend_base)
    if not res.get("ok"):
        parts = [x for x in (res.get("errors") or []) if x]
        raise ValueError("员工沙箱未通过: " + ("; ".join(parts) if parts else "未知原因"))


def run_employee_sandbox_on_library_mod(mod_dir: Path, *, probe_http: bool, backend_base: Optional[str]) -> Dict[str, Any]:
    """对已位于 library 的 Mod 目录检查（不拷贝）。"""
    mod_dir = mod_dir.resolve()
    data, err = read_manifest(mod_dir)
    if err or not data:
        return {
            "ok": False,
            "errors": [err or "manifest 无效"],
            "warnings": [],
            "static": {},
            "http": {},
        }
    static = run_static_employee_sandbox(mod_dir)
    mid = str(data.get("id") or mod_dir.name).strip() or mod_dir.name
    http: Dict[str, Any] = {}
    if static.get("ok") and probe_http and backend_base and not static.get("skipped"):
        http = run_http_employee_sandbox(mid, mod_dir, data, backend_base)
    merge_errors = list(static.get("errors") or [])
    if static.get("ok") and http and not http.get("skipped") and not http.get("ok"):
        merge_errors.append("HTTP 探测未全部通过")
    ok = bool(static.get("ok")) and (not http or http.get("skipped") or http.get("ok", True))
    return {
        "ok": ok,
        "skipped": bool(static.get("skipped")),
        "errors": merge_errors,
        "warnings": list(static.get("warnings") or []),
        "static": static,
        "http": http,
        "mod_id": mid,
    }
