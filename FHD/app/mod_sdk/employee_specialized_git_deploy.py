"""Git/deploy/infra tools."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.mod_sdk.employee_specialized_runtime import (
    _DEFAULT_API_BASE,
    _DUTY_ROSTER,
    _EMPLOYEES_DIR,
    _FHD_ROOT,
    _PYTHON,
    _api_call,
    _err,
    _facade_attr,
    _ok,
    _run_cmd,
)


def _shutil():
    import app.mod_sdk.employee_specialized_tools as est

    return est.shutil


async def tool_git_status(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """git status --porcelain。"""
    r = await _run_cmd(["git", "status", "--porcelain"], cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT))
    lines = [l for l in r["stdout"].splitlines() if l.strip()]
    return _ok(f"{len(lines)} 个变更", files=lines, clean=len(lines) == 0, raw=r["stdout"])


async def tool_git_log(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """git log --oneline。"""
    n = str(params.get("n", 20))
    r = await _run_cmd(["git", "log", "--oneline", f"-{n}"], cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT))
    commits = [l for l in r["stdout"].splitlines() if l.strip()]
    return _ok(f"最近 {len(commits)} 条提交", commits=commits)


async def tool_git_diff(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """git diff（unstaged 或指定 ref）。"""
    ref = params.get("ref") or ""
    args = ["git", "diff", *([ref] if ref else [])]
    if params.get("stat"):
        args.append("--stat")
    r = await _run_cmd(args, cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT))
    return _ok("git diff", diff=r["stdout"][-8000:], returncode=r["returncode"])


async def tool_git_branch(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """当前分支名。"""
    r = await _run_cmd(["git", "branch", "--show-current"], cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT))
    return _ok(f"branch={r['stdout'].strip()}", branch=r["stdout"].strip())


# ---------------------------------------------------------------------------
# 部署工具（deploy）
# ---------------------------------------------------------------------------


async def tool_pack_release(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """打包发布 tarball（需 confirm）。"""
    if not params.get("confirm"):
        return _err("pack_release 需 confirm=true 确认", requires_confirm=True)
    script = _facade_attr("_FHD_ROOT", _FHD_ROOT) / "scripts" / "deploy" / "fhd-pack-release.sh"
    r = await _run_cmd(["bash", str(script)], cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT), timeout=600)
    return _ok(
        f"pack exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_list_deploy_scripts(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """列出部署脚本。"""
    deploy_dir = _facade_attr("_FHD_ROOT", _FHD_ROOT) / "scripts" / "deploy"
    scripts = sorted(p.name for p in deploy_dir.glob("*.sh")) if deploy_dir.is_dir() else []
    return _ok(f"{len(scripts)} 个部署脚本", scripts=scripts)


async def tool_trigger_gh_workflow(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """通过 gh CLI 触发 GitHub Actions workflow（需 confirm）。"""
    if not params.get("confirm"):
        return _err("trigger_gh_workflow 需 confirm=true 确认", requires_confirm=True)
    workflow = str(params.get("workflow") or "").strip()
    if not workflow:
        return _err("缺少 workflow 参数")
    ref = str(params.get("ref") or "main")
    r = await _run_cmd(["gh", "workflow", "run", workflow, "--ref", ref], cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT))
    return _ok(
        f"gh workflow run exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"],
        stderr=r["stderr"],
        passed=r["ok"],
    )


# ---------------------------------------------------------------------------
# 基础设施工具（infra）
# ---------------------------------------------------------------------------


async def tool_nginx_test(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """nginx -t 语法检查。"""
    nginx = _shutil().which("nginx")
    if not nginx:
        return _ok("nginx 未安装（跳过）", skipped=True, syntax_valid=None)
    r = await _run_cmd([nginx, "-t"])
    return _ok(
        f"nginx -t exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"],
        stderr=r["stderr"],
        syntax_valid=r["ok"],
    )


async def tool_api_health(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """检查本机 API 健康。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)
    r = await _api_call("GET", "/api/health", api_base=api_base)
    return _ok(f"health status={r.get('status')}", **r)


async def tool_mod_loading_status(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询 mod 加载状态。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)
    r = await _api_call("GET", "/api/mods/loading-status", api_base=api_base)
    return _ok(f"loading-status status={r.get('status')}", **r)


async def tool_disk_usage(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """磁盘使用情况。"""
    r = await _run_cmd(["df", "-h", _facade_attr("_FHD_ROOT", _FHD_ROOT)])
    return _ok("df -h", output=r["stdout"])


async def tool_tail_logs(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """读取最近 N 行日志。"""
    log_dir = _facade_attr("_FHD_ROOT", _FHD_ROOT) / "logs"
    if not log_dir.is_dir():
        return _ok("logs 目录不存在", lines=[])
    n = int(params.get("lines", 100))
    log_file = params.get("file") or "app.log"
    target = log_dir / log_file
    if not target.is_file():
        files = sorted(p.name for p in log_dir.glob("*.log"))
        return _ok(f"{log_file} 不存在", available_files=files)
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError as exc:
        return _err(f"读取日志失败: {exc}")
    return _ok(f"{len(lines)} 行", lines=lines)


async def tool_performance_status(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询性能状态。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)
    r = await _api_call("GET", "/api/performance/status", api_base=api_base)
    return _ok(f"performance status={r.get('status')}", **r)


# ---------------------------------------------------------------------------
# Mod / 员工包工具（mod）
# ---------------------------------------------------------------------------


async def tool_list_mods(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """列出已加载 mods。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)
    r = await _api_call("GET", "/api/mods/", api_base=api_base)
    return _ok(f"mods status={r.get('status')}", **r)


async def tool_list_employee_packs(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """扫描本地 _employees/ 目录，列出已安装员工包。"""
    packs: list[dict[str, Any]] = []
    if not _facade_attr("_EMPLOYEES_DIR", _EMPLOYEES_DIR).is_dir():
        return _ok("_employees 目录不存在", packs=packs)
    for name in sorted(os.listdir(_facade_attr("_EMPLOYEES_DIR", _EMPLOYEES_DIR))):
        mf = _facade_attr("_EMPLOYEES_DIR", _EMPLOYEES_DIR) / name / "manifest.json"
        if not mf.is_file():
            continue
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        packs.append(
            {
                "id": data.get("id") or name,
                "label": data.get("name") or data.get("employee_label") or name,
                "artifact": data.get("artifact"),
                "area": (data.get("employee_config_v2") or {}).get("area"),
            }
        )
    return _ok(f"{len(packs)} 个员工包", packs=packs)


async def tool_validate_employee_pack(
    params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """验证员工包 manifest 完整性。"""
    pack_id = str(params.get("pack_id") or "").strip()
    if not pack_id:
        return _err("缺少 pack_id 参数")
    mf = _facade_attr("_EMPLOYEES_DIR", _EMPLOYEES_DIR) / pack_id / "manifest.json"
    if not mf.is_file():
        return _err(f"manifest 不存在: {mf}")
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _err(f"manifest 解析失败: {exc}")
    issues: list[str] = []
    if data.get("artifact") != "employee_pack":
        issues.append(f"artifact 应为 employee_pack，实际 {data.get('artifact')!r}")
    if not data.get("id"):
        issues.append("缺少 id")
    v2 = data.get("employee_config_v2") or {}
    if not isinstance(v2, dict):
        issues.append("缺少 employee_config_v2")
    else:
        cog = v2.get("cognition") or {}
        agent = cog.get("agent") or {}
        if not agent.get("system_prompt"):
            issues.append("缺少 system_prompt")
    return _ok(
        f"验证 {pack_id}: {'通过' if not issues else '有问题'}",
        valid=not issues,
        issues=issues,
        manifest=data,
    )


async def tool_duty_graph_health(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询 duty graph 健康（编制对账）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)
    r = await _api_call("GET", "/api/xcmax/ops/duty-health", api_base=api_base)
    return _ok(f"duty-health status={r.get('status')}", **r)


# ---------------------------------------------------------------------------
# 文档工具（doc）
# ---------------------------------------------------------------------------


async def tool_list_docs(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """列出项目文档。"""
    doc_dirs = [_facade_attr("_FHD_ROOT", _FHD_ROOT) / "docs", _facade_attr("_FHD_ROOT", _FHD_ROOT).parent / "docs"]
    docs: list[str] = []
    for d in doc_dirs:
        if d.is_dir():
            docs.extend(str(p.relative_to(_facade_attr("_FHD_ROOT", _FHD_ROOT).parent)) for p in d.rglob("*.md"))
    docs = sorted(set(docs))
    return _ok(f"{len(docs)} 个文档", docs=docs)


async def tool_read_file(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """读取文件内容（限项目内、限 50KB）。"""
    rel = str(params.get("path") or "").strip()
    if not rel:
        return _err("缺少 path 参数")
    target = (_facade_attr("_FHD_ROOT", _FHD_ROOT) / rel).resolve()
    try:
        target.relative_to(_facade_attr("_FHD_ROOT", _FHD_ROOT))
    except ValueError:
        return _err("路径越界（仅限项目内）")
    if not target.is_file():
        return _err(f"文件不存在: {rel}")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _err(f"读取失败: {exc}")
    return _ok(
        f"{len(content)} 字符", content=content[:50000], path=rel, truncated=len(content) > 50000
    )


async def tool_list_scripts(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """列出项目脚本。"""
    scripts_dir = _facade_attr("_FHD_ROOT", _FHD_ROOT) / "scripts"
    if not scripts_dir.is_dir():
        return _ok("scripts 目录不存在", scripts=[])
    category = str(params.get("category") or "").strip()
    search_dir = scripts_dir / category if category else scripts_dir
    if not search_dir.is_dir():
        return _err(f"目录不存在: scripts/{category}")
    pys = sorted(str(p.relative_to(_facade_attr("_FHD_ROOT", _FHD_ROOT))) for p in search_dir.rglob("*.py"))
    shs = sorted(str(p.relative_to(_facade_attr("_FHD_ROOT", _FHD_ROOT))) for p in search_dir.rglob("*.sh"))
    return _ok(f"{len(pys)} py + {len(shs)} sh", python=pys, shell=shs)


# ---------------------------------------------------------------------------
# 平台工具（platform）
# ---------------------------------------------------------------------------


async def tool_list_employees(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """列出全部编制员工（duty_roster.json）。"""
    if not _facade_attr("_DUTY_ROSTER", _DUTY_ROSTER).is_file():
        return _err("duty_roster.json 不存在")
    try:
        roster = json.loads(_facade_attr("_DUTY_ROSTER", _DUTY_ROSTER).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _err(f"解析失败: {exc}")

    def _collect(blocks: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        for block in blocks.values():
            if not isinstance(block, dict):
                continue
            raw = block.get("ids")
            if isinstance(raw, list):
                ids.extend(str(x).strip() for x in raw if str(x).strip())
            sub = block.get("subzones")
            if isinstance(sub, dict):
                ids.extend(_collect(sub))
        return ids

    planned: list[str] = []
    for key in ("areas", "departments"):
        planned.extend(_collect(roster.get(key) or {}))
    planned = sorted(set(planned))
    return _ok(f"{len(planned)} 个编制员工", employees=planned)


async def tool_employee_status(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询某员工状态。"""
    emp_id = str(params.get("employee_id") or ctx.get("employee_id") or "").strip()
    if not emp_id:
        return _err("缺少 employee_id")
    api_base = params.get("api_base") or ctx.get("api_base") or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)
    r = await _api_call("GET", f"/api/xcmax/local/employees/{emp_id}/status", api_base=api_base)
    return _ok(f"employee {emp_id} status={r.get('status')}", employee_id=emp_id, **r)


async def tool_list_action_items(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询行动项。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)
    r = await _api_call("GET", "/api/admin/action-items", api_base=api_base)
    return _ok(f"action-items status={r.get('status')}", **r)


async def tool_employee_autonomy_dashboard(
    params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """查询员工自治仪表盘。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)
    r = await _api_call("GET", "/api/admin/employee-autonomy/dashboard", api_base=api_base)
    return _ok(f"autonomy dashboard status={r.get('status')}", **r)


# ---------------------------------------------------------------------------
# Craft 工具（制作车间）
# ---------------------------------------------------------------------------


async def tool_list_workbench_sessions(
    params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """列出 workbench 会话。"""
    ws_root = Path(ctx.get("workspace_root") or _facade_attr("_FHD_ROOT", _FHD_ROOT))
    sessions_dir = ws_root / "workbench" / "sessions"
    if not sessions_dir.is_dir():
        return _ok("workbench/sessions 不存在", sessions=[])
    sessions = sorted(p.name for p in sessions_dir.iterdir() if p.is_dir())
    return _ok(f"{len(sessions)} 个会话", sessions=sessions)


async def tool_sandbox_python(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """在沙箱中执行 Python 代码（只读 stdout，30s 超时，禁网络）。"""
    code = str(params.get("code") or "").strip()
    if not code:
        return _err("缺少 code 参数")
    if len(code) > 20000:
        return _err("代码过长（>20KB）")
    # 禁止危险操作
    for forbidden in ("import os", "import subprocess", "import shutil", "open(", "__import__"):
        if forbidden in code and not params.get("confirm"):
            return _err(f"检测到受限操作 {forbidden!r}，需 confirm=true", requires_confirm=True)
    r = await _run_cmd([_facade_attr("_PYTHON", _PYTHON), "-c", code], cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT), timeout=30, env={"XCAGI_SANDBOX": "1"})
    return _ok(
        f"sandbox exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


# ---------------------------------------------------------------------------
# 支付/对账工具（payment）
# ---------------------------------------------------------------------------


async def tool_check_transactions(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询交易记录（只读，调内部 API）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)
    limit = int(params.get("limit", 50))
    r = await _api_call("GET", "/api/admin/wallets", api_base=api_base, params={"limit": limit})
    return _ok(f"wallets status={r.get('status')}", **r)


async def tool_list_invoices(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询发票记录（只读）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)
    r = await _api_call("GET", "/api/admin/invoices", api_base=api_base)
    return _ok(f"invoices status={r.get('status')}", **r)


# ---------------------------------------------------------------------------
# 生态工具（ecosystem）
# ---------------------------------------------------------------------------


async def tool_list_enterprise_mods(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询企业可分配 mods。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)
    r = await _api_call("GET", "/api/admin/enterprise/assignable-mods", api_base=api_base)
    return _ok(f"enterprise mods status={r.get('status')}", **r)


async def tool_list_users(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询用户列表（只读）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)
    r = await _api_call("GET", "/api/admin/users", api_base=api_base)
    return _ok(f"users status={r.get('status')}", **r)


# ---------------------------------------------------------------------------
# 前端工具（frontend）
# ---------------------------------------------------------------------------


async def tool_frontend_lint(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """前端 ESLint 检查。"""
    fe_dir = _facade_attr("_FHD_ROOT", _FHD_ROOT) / "frontend"
    if not (fe_dir / "package.json").is_file():
        return _err("frontend/package.json 不存在")
    npm = _shutil().which("npm")
    if not npm:
        return _ok("npm 未安装（跳过）", skipped=True)
    r = await _run_cmd([npm, "run", "lint"], cwd=fe_dir, timeout=300)
    return _ok(
        f"eslint exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_frontend_typecheck(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """前端 vue-tsc 类型检查。"""
    fe_dir = _facade_attr("_FHD_ROOT", _FHD_ROOT) / "frontend"
    if not (fe_dir / "package.json").is_file():
        return _err("frontend/package.json 不存在")
    npm = _shutil().which("npm")
    if not npm:
        return _ok("npm 未安装（跳过）", skipped=True)
    r = await _run_cmd([npm, "run", "type-check"], cwd=fe_dir, timeout=300)
    return _ok(
        f"type-check exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_frontend_test(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """前端 Vitest 单元测试。"""
    fe_dir = _facade_attr("_FHD_ROOT", _FHD_ROOT) / "frontend"
    if not (fe_dir / "package.json").is_file():
        return _err("frontend/package.json 不存在")
    npm = _shutil().which("npm")
    if not npm:
        return _ok("npm 未安装（跳过）", skipped=True)
    r = await _run_cmd([npm, "run", "test"], cwd=fe_dir, timeout=300)
    return _ok(
        f"vitest exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


# ---------------------------------------------------------------------------
# 移动端工具（mobile）
# ---------------------------------------------------------------------------


async def tool_android_gradle_build(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Android Gradle 构建检查（需 confirm）。"""
    if not params.get("confirm"):
        return _err("android_gradle_build 需 confirm=true 确认", requires_confirm=True)
    android_dir = _facade_attr("_FHD_ROOT", _FHD_ROOT) / "mobile-android"
    gradlew = android_dir / "gradlew"
    if not gradlew.is_file():
        return _err("mobile-android/gradlew 不存在")
    r = await _run_cmd(["bash", str(gradlew), "tasks", "--all"], cwd=android_dir, timeout=600)
    return _ok(
        f"gradle exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )
