# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.mod_sdk.employee_specialized_tools")


async def tool_list_workbench_sessions(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """列出 workbench 会话。"""
    ws_root = _facade().Path(ctx.get("workspace_root") or _facade()._FHD_ROOT)
    sessions_dir = ws_root / "workbench" / "sessions"
    if not sessions_dir.is_dir():
        return _facade()._ok("workbench/sessions 不存在", sessions=[])
    sessions = sorted(p.name for p in sessions_dir.iterdir() if p.is_dir())
    return _facade()._ok(f"{len(sessions)} 个会话", sessions=sessions)


async def tool_sandbox_python(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """在沙箱中执行 Python 代码（只读 stdout，30s 超时，禁网络）。"""
    code = str(params.get("code") or "").strip()
    if not code:
        return _facade()._err("缺少 code 参数")
    if len(code) > 20000:
        return _facade()._err("代码过长（>20KB）")
    for forbidden in ("import os", "import subprocess", "import shutil", "open(", "__import__"):
        if forbidden in code and (not params.get("confirm")):
            return _facade()._err(
                f"检测到受限操作 {forbidden!r}，需 confirm=true", requires_confirm=True
            )
    r = await _facade()._run_cmd(
        [_facade()._PYTHON, "-c", code],
        cwd=_facade()._FHD_ROOT,
        timeout=30,
        env={"XCAGI_SANDBOX": "1"},
    )
    return _facade()._ok(
        f"sandbox exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_check_transactions(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询交易记录（只读，调内部 API）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade()._DEFAULT_API_BASE
    limit = int(params.get("limit", 50))
    r = await _facade()._api_call(
        "GET", "/api/admin/wallets", api_base=api_base, params={"limit": limit}
    )
    return _facade()._ok(f"wallets status={r.get('status')}", **r)


async def tool_list_invoices(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询发票记录（只读）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call("GET", "/api/admin/invoices", api_base=api_base)
    return _facade()._ok(f"invoices status={r.get('status')}", **r)


async def tool_list_enterprise_mods(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询企业可分配 mods。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call("GET", "/api/admin/enterprise/assignable-mods", api_base=api_base)
    return _facade()._ok(f"enterprise mods status={r.get('status')}", **r)


async def tool_list_users(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询用户列表（只读）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call("GET", "/api/admin/users", api_base=api_base)
    return _facade()._ok(f"users status={r.get('status')}", **r)


async def tool_frontend_lint(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """前端 ESLint 检查。"""
    fe_dir = _facade()._FHD_ROOT / "frontend"
    if not (fe_dir / "package.json").is_file():
        return _facade()._err("frontend/package.json 不存在")
    npm = _facade().shutil.which("npm")
    if not npm:
        return _facade()._ok("npm 未安装（跳过）", skipped=True)
    r = await _facade()._run_cmd([npm, "run", "lint"], cwd=fe_dir, timeout=300)
    return _facade()._ok(
        f"eslint exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_frontend_typecheck(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """前端 vue-tsc 类型检查。"""
    fe_dir = _facade()._FHD_ROOT / "frontend"
    if not (fe_dir / "package.json").is_file():
        return _facade()._err("frontend/package.json 不存在")
    npm = _facade().shutil.which("npm")
    if not npm:
        return _facade()._ok("npm 未安装（跳过）", skipped=True)
    r = await _facade()._run_cmd([npm, "run", "type-check"], cwd=fe_dir, timeout=300)
    return _facade()._ok(
        f"type-check exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_frontend_test(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """前端 Vitest 单元测试。"""
    fe_dir = _facade()._FHD_ROOT / "frontend"
    if not (fe_dir / "package.json").is_file():
        return _facade()._err("frontend/package.json 不存在")
    npm = _facade().shutil.which("npm")
    if not npm:
        return _facade()._ok("npm 未安装（跳过）", skipped=True)
    r = await _facade()._run_cmd([npm, "run", "test"], cwd=fe_dir, timeout=300)
    return _facade()._ok(
        f"vitest exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_android_gradle_build(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """Flutter Android debug 构建检查（外部工具名为兼容既有调用保留）。"""
    if not params.get("confirm"):
        return _facade()._err("android_gradle_build 需 confirm=true 确认", requires_confirm=True)
    flutter_dir = _facade()._FHD_ROOT / "mobile-flutter-poc"
    if not (flutter_dir / "pubspec.yaml").is_file():
        return _facade()._err("mobile-flutter-poc/pubspec.yaml 不存在")
    flutter = _facade().shutil.which("flutter")
    if not flutter:
        return _facade()._ok("flutter 未安装（跳过）", skipped=True)
    r = await _facade()._run_cmd([flutter, "build", "apk", "--debug"], cwd=flutter_dir, timeout=900)
    return _facade()._ok(
        f"flutter build apk exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


def _code_write_tools() -> frozenset[str]:
    global _CODE_WRITE_TOOLS_LAZY
    if _facade()._CODE_WRITE_TOOLS_LAZY is None:
        try:
            from app.application.employee_runtime.tool_scope import CODE_WRITE_TOOLS

            _facade()._CODE_WRITE_TOOLS_LAZY = CODE_WRITE_TOOLS
        except ImportError:
            _facade()._CODE_WRITE_TOOLS_LAZY = frozenset({"patch_file", "write_file"})
    return _facade()._CODE_WRITE_TOOLS_LAZY


async def tool_write_file(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """写入文件内容（受 scope_globs 约束，需 confirm=True 二次确认）。"""
    if not params.get("confirm"):
        return _facade()._err("write_file 需 params.confirm=True 二次确认")
    rel_path = str(params.get("path") or "").strip()
    content = str(params.get("content") or "")
    if not rel_path:
        return _facade()._err("缺少 params.path")
    workspace_root = str(ctx.get("workspace_root") or _facade().os.getcwd())
    root = _facade().Path(workspace_root).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return _facade()._err(f"路径 {rel_path} 越出 workspace_root")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        return _facade()._err(f"写入失败: {exc!r}")
    return _facade()._ok(
        f"已写入 {rel_path}（{len(content)} 字符）",
        path=rel_path,
        bytes_written=len(content.encode()),
    )


async def tool_patch_file(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """应用 unified diff patch 到文件（受 scope_globs 约束，需 confirm=True）。"""
    if not params.get("confirm"):
        return _facade()._err("patch_file 需 params.confirm=True 二次确认")
    rel_path = str(params.get("path") or "").strip()
    patch = str(params.get("patch") or "")
    if not rel_path or not patch:
        return _facade()._err("缺少 params.path 或 params.patch")
    workspace_root = str(ctx.get("workspace_root") or _facade().os.getcwd())
    root = _facade().Path(workspace_root).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return _facade()._err(f"路径 {rel_path} 越出 workspace_root")
    if not target.is_file():
        return _facade()._err(f"目标文件不存在: {rel_path}")
    patch_tmp = root / f".tmp-patch-{_facade().os.getpid()}.diff"
    try:
        patch_tmp.write_text(patch, encoding="utf-8")
        check = await _facade()._run_cmd(
            ["git", "apply", "--check", str(patch_tmp)], cwd=root, timeout=15
        )
        if not check.get("ok"):
            return _facade()._err(f"patch 校验失败: {check.get('stderr', '')[:500]}")
        apply = await _facade()._run_cmd(["git", "apply", str(patch_tmp)], cwd=root, timeout=15)
        if not apply.get("ok"):
            return _facade()._err(f"patch 应用失败: {apply.get('stderr', '')[:500]}")
    finally:
        try:
            patch_tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return _facade()._ok(f"已应用 patch 到 {rel_path}", path=rel_path)


async def _check_write_gate(
    employee_id: str,
    tool_name: str,
    params: dict[str, _facade().Any],
    ctx: dict[str, _facade().Any],
) -> dict[str, _facade().Any]:
    """对代码修改工具检查 workspace_guard + write_approval gate。

    从 EmployeeRegistry 加载 manifest，构造 gate 并强制 scope_globs / forbidden_globs / 审批。
    gate 失败时返回 {ok: False, reason}；通过返回 {ok: True}。
    """
    try:
        from app.application.employee_runtime.workspace_guard import build_employee_gate
        from app.application.employee_runtime.write_approval import (
            build_write_approval_gate,
            compose_gates,
        )
        from app.infrastructure.mods.employee_registry import EmployeeRegistry
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mgr = get_mod_manager()
        manifest: dict[str, _facade().Any] | None = None
        roots: list[str] = []
        try:
            roots = list(mgr.all_mods_roots() or [])
        except _facade().RECOVERABLE_ERRORS:
            roots = []
        if not roots:
            primary = getattr(mgr, "mods_root", None)
            if primary:
                roots = [primary]
        for mods_root in roots:
            if not mods_root:
                continue
            registry = EmployeeRegistry(mods_root)
            for pack in registry.list_packs():
                if str(pack.get("id") or "") == employee_id:
                    manifest = pack
                    break
            if manifest:
                break
        if not manifest:
            return {"ok": False, "reason": f"未找到员工 {employee_id} 的 manifest，无法校验 scope"}
        config = manifest.get("employee_config_v2") or {}
        workspace_root = str(ctx.get("workspace_root") or _facade().os.getcwd())
        ws_gate = build_employee_gate(employee_id, manifest, config, workspace_root)
        write_gate = build_write_approval_gate(employee_id, params)
        gate = compose_gates(ws_gate, write_gate)
        if gate is None:
            return {"ok": True}
        return _facade().cast("dict[str, Any]", gate(tool_name, params))
    except _facade().RECOVERABLE_ERRORS as exc:
        return {"ok": False, "reason": f"gate 检查异常: {exc!r}"}


def _mask_secret(val: str) -> str:
    """脱敏：sk-abc123xyz → sk-***xyz（保留前 3 + 后 3）。"""
    if not val:
        return ""
    if len(val) <= 8:
        return "***"
    return f"{val[:3]}***{val[-3:]}"


def _read_env_file(env_path: _facade().Path) -> dict[str, str]:
    """解析 .env 文件为 dict（不污染 os.environ）。"""
    out: dict[str, str] = {}
    if not env_path.is_file():
        return out
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip("'\"")
            if k:
                out[k] = v
    except OSError:
        pass
    return out


def _provider_has_key(profile: dict[str, _facade().Any], env: dict[str, str]) -> str | None:
    """检查 provider 是否配了 key，返回第一个非空 key（不脱敏）。"""
    for k in profile["env_keys"]:
        v = env.get(k)
        if v:
            return v
    return None


def _provider_base_url(profile: dict[str, _facade().Any], env: dict[str, str]) -> str:
    """获取 provider 的 base_url（env 覆盖 default）。"""
    env_key = profile.get("base_url_env")
    if env_key:
        v = env.get(env_key)
        if v:
            return v
    return _facade().cast("str", profile["base_url_default"])
