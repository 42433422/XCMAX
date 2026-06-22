"""AI 员工专属工具调用库。

为 52 个编制员工提供真实的专属工具实现（subprocess / httpx / 文件操作），
而非仅靠 LLM system_prompt 驱动。工具按域分组，每个员工按职责注册 2-4 个工具。

设计原则：
- 真实执行：跑真实命令（pytest/ruff/mypy/git）、调真实内部 API、读写真实文件
- 只读优先：涉及写操作的工具需 payload.confirm=True 二次确认
- 零侵入员工 .py：specialized handler 在 executor 层拦截，不修改 52 个员工文件
- 安全边界：subprocess 限定白名单命令，httpx 只打本机/白名单 host
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

_FHD_ROOT = Path(__file__).resolve().parents[2]  # .../FHD
_SCRIPTS = _FHD_ROOT / "scripts"
_VENV_PYTHON = str(_FHD_ROOT / ".venv" / "bin" / "python")
_PYTHON = _VENV_PYTHON if os.path.isfile(_VENV_PYTHON) else sys.executable
_EMPLOYEES_DIR = _FHD_ROOT / "mods" / "_employees"
_DUTY_ROSTER = _FHD_ROOT / "config" / "duty_roster.json"

# 本机 API base（executor 注入的 ctx 可覆盖）
_DEFAULT_API_BASE = os.environ.get("XCAGI_EMPLOYEE_API_BASE", "http://127.0.0.1:5102")

# subprocess 超时（秒）
_DEFAULT_TIMEOUT = 120


# ---------------------------------------------------------------------------
# 工具结果构造
# ---------------------------------------------------------------------------


def _ok(summary: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True, "summary": summary[:4000]}
    out.update(extra)
    return out


def _err(error: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": error[:1000]}
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# subprocess 执行器
# ---------------------------------------------------------------------------


async def _run_cmd(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """执行命令并返回结构化结果。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **(env or {})},
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
        stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
        return {
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "ok": proc.returncode == 0,
        }
    except TimeoutError:
        return {"returncode": -1, "stdout": "", "stderr": f"timeout after {timeout}s", "ok": False}
    except FileNotFoundError as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc), "ok": False}
    except Exception as exc:  # noqa: BLE001  工具执行边界：任何异常都转为结构化结果
        return {"returncode": -1, "stdout": "", "stderr": repr(exc), "ok": False}


async def _run_python_script(script: str | Path, *extra_args: str, **kw: Any) -> dict[str, Any]:
    """用项目 venv python 跑一个脚本。"""
    return await _run_cmd([_PYTHON, str(script), *extra_args], **kw)


# ---------------------------------------------------------------------------
# httpx 内部 API 调用
# ---------------------------------------------------------------------------


async def _api_call(
    method: str, path: str, *, api_base: str | None = None, **kw: Any
) -> dict[str, Any]:
    if httpx is None:
        return {"ok": False, "error": "httpx 未安装"}
    base = (api_base or _DEFAULT_API_BASE).rstrip("/")
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
    try:
        async with httpx.AsyncClient(timeout=kw.pop("timeout", 30)) as client:
            resp = await client.request(method, url, **kw)
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001  JSON 解析失败时降级为文本
                body = resp.text
            return {"ok": resp.is_success, "status": resp.status_code, "body": body}
    except Exception as exc:  # noqa: BLE001  API 调用边界：网络/解析异常转结构化结果
        return {"ok": False, "error": repr(exc)}


# ---------------------------------------------------------------------------
# 质量工具（quality）
# ---------------------------------------------------------------------------


async def tool_run_pytest(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """运行 pytest 测试套件。"""
    args = params.get("args") or ["tests/", "-q", "--tb=short"]
    if isinstance(args, str):
        args = args.split()
    env = {"XCAGI_SKIP_LEGACY_COMPAT_ROUTES": "1"}
    extra_env = params.get("env") or {}
    if isinstance(extra_env, dict):
        env.update(extra_env)
    r = await _run_cmd(
        [_PYTHON, "-m", "pytest", *[str(a) for a in args]],
        cwd=_FHD_ROOT,
        timeout=int(params.get("timeout", 600)),
        env=env,
    )
    return _ok(
        f"pytest exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-8000:],
        stderr=r["stderr"][-4000:],
        passed=r["ok"],
    )


async def tool_run_ruff_check(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """运行 ruff lint 检查。"""
    targets = params.get("targets") or ["app/", "tests/"]
    if isinstance(targets, str):
        targets = targets.split()
    r = await _run_cmd([_PYTHON, "-m", "ruff", "check", *[str(t) for t in targets]], cwd=_FHD_ROOT)
    return _ok(
        f"ruff check exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_run_ruff_format(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """运行 ruff format 检查。"""
    targets = params.get("targets") or ["app/", "tests/"]
    if isinstance(targets, str):
        targets = targets.split()
    r = await _run_cmd(
        [_PYTHON, "-m", "ruff", "format", "--check", *[str(t) for t in targets]], cwd=_FHD_ROOT
    )
    return _ok(
        f"ruff format exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_run_mypy(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """运行 mypy 类型检查。"""
    targets = params.get("targets") or ["app/"]
    if isinstance(targets, str):
        targets = targets.split()
    r = await _run_cmd(
        [_PYTHON, "-m", "mypy", *[str(t) for t in targets]], cwd=_FHD_ROOT, timeout=300
    )
    return _ok(
        f"mypy exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-8000:],
        stderr=r["stderr"][-4000:],
        passed=r["ok"],
    )


async def tool_check_coverage(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """检查覆盖率棘轮（只升不降）。"""
    r = await _run_python_script(_SCRIPTS / "dev" / "coverage_ratchet.py", "--check", cwd=_FHD_ROOT)
    return _ok(
        f"coverage ratchet exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_count_type_debt(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """统计类型债务。"""
    r = await _run_python_script(_SCRIPTS / "dev" / "count_type_debt.py", cwd=_FHD_ROOT)
    return _ok(
        f"type debt exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_count_raw_sql(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """统计 SQL 债务。"""
    r = await _run_python_script(_SCRIPTS / "dev" / "count_raw_sql.py", cwd=_FHD_ROOT)
    return _ok(
        f"raw sql exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_run_arch_fitness(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """运行架构适配度检查。"""
    r = await _run_python_script(_FHD_ROOT / "scripts" / "arch_fitness.py", cwd=_FHD_ROOT)
    return _ok(
        f"arch fitness exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_verify_version_anchors(
    params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """校验版本锚点。"""
    r = await _run_python_script(_SCRIPTS / "dev" / "verify_version_anchors.py", cwd=_FHD_ROOT)
    return _ok(
        f"version anchors exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_verify_employee_contract(
    params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """验证员工契约。"""
    r = await _run_python_script(_SCRIPTS / "dev" / "verify_employee_contract.py", cwd=_FHD_ROOT)
    return _ok(
        f"employee contract exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_mutation_kill_report(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """变异测试杀死率报告。"""
    r = await _run_python_script(
        _SCRIPTS / "dev" / "mutation_kill_report.py", cwd=_FHD_ROOT, timeout=600
    )
    return _ok(
        f"mutation kill exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


# ---------------------------------------------------------------------------
# Git 工具
# ---------------------------------------------------------------------------


async def tool_git_status(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """git status --porcelain。"""
    r = await _run_cmd(["git", "status", "--porcelain"], cwd=_FHD_ROOT)
    lines = [l for l in r["stdout"].splitlines() if l.strip()]
    return _ok(f"{len(lines)} 个变更", files=lines, clean=len(lines) == 0, raw=r["stdout"])


async def tool_git_log(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """git log --oneline。"""
    n = str(params.get("n", 20))
    r = await _run_cmd(["git", "log", "--oneline", f"-{n}"], cwd=_FHD_ROOT)
    commits = [l for l in r["stdout"].splitlines() if l.strip()]
    return _ok(f"最近 {len(commits)} 条提交", commits=commits)


async def tool_git_diff(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """git diff（unstaged 或指定 ref）。"""
    ref = params.get("ref") or ""
    args = ["git", "diff", *([ref] if ref else [])]
    if params.get("stat"):
        args.append("--stat")
    r = await _run_cmd(args, cwd=_FHD_ROOT)
    return _ok("git diff", diff=r["stdout"][-8000:], returncode=r["returncode"])


async def tool_git_branch(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """当前分支名。"""
    r = await _run_cmd(["git", "branch", "--show-current"], cwd=_FHD_ROOT)
    return _ok(f"branch={r['stdout'].strip()}", branch=r["stdout"].strip())


# ---------------------------------------------------------------------------
# 部署工具（deploy）
# ---------------------------------------------------------------------------


async def tool_pack_release(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """打包发布 tarball（需 confirm）。"""
    if not params.get("confirm"):
        return _err("pack_release 需 confirm=true 确认", requires_confirm=True)
    script = _FHD_ROOT / "scripts" / "deploy" / "fhd-pack-release.sh"
    r = await _run_cmd(["bash", str(script)], cwd=_FHD_ROOT, timeout=600)
    return _ok(
        f"pack exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_list_deploy_scripts(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """列出部署脚本。"""
    deploy_dir = _FHD_ROOT / "scripts" / "deploy"
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
    r = await _run_cmd(["gh", "workflow", "run", workflow, "--ref", ref], cwd=_FHD_ROOT)
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
    nginx = shutil.which("nginx")
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
    api_base = params.get("api_base") or ctx.get("api_base") or _DEFAULT_API_BASE
    r = await _api_call("GET", "/api/health", api_base=api_base)
    return _ok(f"health status={r.get('status')}", **r)


async def tool_mod_loading_status(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询 mod 加载状态。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _DEFAULT_API_BASE
    r = await _api_call("GET", "/api/mods/loading-status", api_base=api_base)
    return _ok(f"loading-status status={r.get('status')}", **r)


async def tool_disk_usage(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """磁盘使用情况。"""
    r = await _run_cmd(["df", "-h", _FHD_ROOT])
    return _ok("df -h", output=r["stdout"])


async def tool_tail_logs(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """读取最近 N 行日志。"""
    log_dir = _FHD_ROOT / "logs"
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
    api_base = params.get("api_base") or ctx.get("api_base") or _DEFAULT_API_BASE
    r = await _api_call("GET", "/api/performance/status", api_base=api_base)
    return _ok(f"performance status={r.get('status')}", **r)


# ---------------------------------------------------------------------------
# Mod / 员工包工具（mod）
# ---------------------------------------------------------------------------


async def tool_list_mods(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """列出已加载 mods。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _DEFAULT_API_BASE
    r = await _api_call("GET", "/api/mods/", api_base=api_base)
    return _ok(f"mods status={r.get('status')}", **r)


async def tool_list_employee_packs(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """扫描本地 _employees/ 目录，列出已安装员工包。"""
    packs: list[dict[str, Any]] = []
    if not _EMPLOYEES_DIR.is_dir():
        return _ok("_employees 目录不存在", packs=packs)
    for name in sorted(os.listdir(_EMPLOYEES_DIR)):
        mf = _EMPLOYEES_DIR / name / "manifest.json"
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
    mf = _EMPLOYEES_DIR / pack_id / "manifest.json"
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
    api_base = params.get("api_base") or ctx.get("api_base") or _DEFAULT_API_BASE
    r = await _api_call("GET", "/api/xcmax/ops/duty-health", api_base=api_base)
    return _ok(f"duty-health status={r.get('status')}", **r)


# ---------------------------------------------------------------------------
# 文档工具（doc）
# ---------------------------------------------------------------------------


async def tool_list_docs(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """列出项目文档。"""
    doc_dirs = [_FHD_ROOT / "docs", _FHD_ROOT.parent / "docs"]
    docs: list[str] = []
    for d in doc_dirs:
        if d.is_dir():
            docs.extend(str(p.relative_to(_FHD_ROOT.parent)) for p in d.rglob("*.md"))
    docs = sorted(set(docs))
    return _ok(f"{len(docs)} 个文档", docs=docs)


async def tool_read_file(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """读取文件内容（限项目内、限 50KB）。"""
    rel = str(params.get("path") or "").strip()
    if not rel:
        return _err("缺少 path 参数")
    target = (_FHD_ROOT / rel).resolve()
    try:
        target.relative_to(_FHD_ROOT)
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
    scripts_dir = _FHD_ROOT / "scripts"
    if not scripts_dir.is_dir():
        return _ok("scripts 目录不存在", scripts=[])
    category = str(params.get("category") or "").strip()
    search_dir = scripts_dir / category if category else scripts_dir
    if not search_dir.is_dir():
        return _err(f"目录不存在: scripts/{category}")
    pys = sorted(str(p.relative_to(_FHD_ROOT)) for p in search_dir.rglob("*.py"))
    shs = sorted(str(p.relative_to(_FHD_ROOT)) for p in search_dir.rglob("*.sh"))
    return _ok(f"{len(pys)} py + {len(shs)} sh", python=pys, shell=shs)


# ---------------------------------------------------------------------------
# 平台工具（platform）
# ---------------------------------------------------------------------------


async def tool_list_employees(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """列出全部编制员工（duty_roster.json）。"""
    if not _DUTY_ROSTER.is_file():
        return _err("duty_roster.json 不存在")
    try:
        roster = json.loads(_DUTY_ROSTER.read_text(encoding="utf-8"))
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
    api_base = params.get("api_base") or ctx.get("api_base") or _DEFAULT_API_BASE
    r = await _api_call("GET", f"/api/xcmax/local/employees/{emp_id}/status", api_base=api_base)
    return _ok(f"employee {emp_id} status={r.get('status')}", employee_id=emp_id, **r)


async def tool_list_action_items(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询行动项。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _DEFAULT_API_BASE
    r = await _api_call("GET", "/api/admin/action-items", api_base=api_base)
    return _ok(f"action-items status={r.get('status')}", **r)


async def tool_employee_autonomy_dashboard(
    params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """查询员工自治仪表盘。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _DEFAULT_API_BASE
    r = await _api_call("GET", "/api/admin/employee-autonomy/dashboard", api_base=api_base)
    return _ok(f"autonomy dashboard status={r.get('status')}", **r)


# ---------------------------------------------------------------------------
# Craft 工具（制作车间）
# ---------------------------------------------------------------------------


async def tool_list_workbench_sessions(
    params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """列出 workbench 会话。"""
    ws_root = Path(ctx.get("workspace_root") or _FHD_ROOT)
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
    r = await _run_cmd([_PYTHON, "-c", code], cwd=_FHD_ROOT, timeout=30, env={"XCAGI_SANDBOX": "1"})
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
    api_base = params.get("api_base") or ctx.get("api_base") or _DEFAULT_API_BASE
    limit = int(params.get("limit", 50))
    r = await _api_call("GET", "/api/admin/wallets", api_base=api_base, params={"limit": limit})
    return _ok(f"wallets status={r.get('status')}", **r)


async def tool_list_invoices(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询发票记录（只读）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _DEFAULT_API_BASE
    r = await _api_call("GET", "/api/admin/invoices", api_base=api_base)
    return _ok(f"invoices status={r.get('status')}", **r)


# ---------------------------------------------------------------------------
# 生态工具（ecosystem）
# ---------------------------------------------------------------------------


async def tool_list_enterprise_mods(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询企业可分配 mods。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _DEFAULT_API_BASE
    r = await _api_call("GET", "/api/admin/enterprise/assignable-mods", api_base=api_base)
    return _ok(f"enterprise mods status={r.get('status')}", **r)


async def tool_list_users(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询用户列表（只读）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _DEFAULT_API_BASE
    r = await _api_call("GET", "/api/admin/users", api_base=api_base)
    return _ok(f"users status={r.get('status')}", **r)


# ---------------------------------------------------------------------------
# 前端工具（frontend）
# ---------------------------------------------------------------------------


async def tool_frontend_lint(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """前端 ESLint 检查。"""
    fe_dir = _FHD_ROOT / "frontend"
    if not (fe_dir / "package.json").is_file():
        return _err("frontend/package.json 不存在")
    npm = shutil.which("npm")
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
    fe_dir = _FHD_ROOT / "frontend"
    if not (fe_dir / "package.json").is_file():
        return _err("frontend/package.json 不存在")
    npm = shutil.which("npm")
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
    fe_dir = _FHD_ROOT / "frontend"
    if not (fe_dir / "package.json").is_file():
        return _err("frontend/package.json 不存在")
    npm = shutil.which("npm")
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
    android_dir = _FHD_ROOT / "mobile-android"
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


# ---------------------------------------------------------------------------
# 代码修改工具（受 scope_globs + write_approval gate 约束）
# ---------------------------------------------------------------------------

# 代码修改工具名集合（SSOT 在 tool_scope.CODE_WRITE_TOOLS，此处延迟导入避免循环）
_CODE_WRITE_TOOLS_LAZY: frozenset[str] | None = None


def _code_write_tools() -> frozenset[str]:
    global _CODE_WRITE_TOOLS_LAZY
    if _CODE_WRITE_TOOLS_LAZY is None:
        try:
            from app.application.employee_runtime.tool_scope import CODE_WRITE_TOOLS

            _CODE_WRITE_TOOLS_LAZY = CODE_WRITE_TOOLS
        except ImportError:
            _CODE_WRITE_TOOLS_LAZY = frozenset({"patch_file", "write_file"})
    return _CODE_WRITE_TOOLS_LAZY


async def tool_write_file(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """写入文件内容（受 scope_globs 约束，需 confirm=True 二次确认）。"""
    if not params.get("confirm"):
        return _err("write_file 需 params.confirm=True 二次确认")
    rel_path = str(params.get("path") or "").strip()
    content = str(params.get("content") or "")
    if not rel_path:
        return _err("缺少 params.path")
    workspace_root = str(ctx.get("workspace_root") or os.getcwd())
    root = Path(workspace_root).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return _err(f"路径 {rel_path} 越出 workspace_root")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:  # noqa: BLE001  IO 边界：转为结构化错误
        return _err(f"写入失败: {exc!r}")
    return _ok(
        f"已写入 {rel_path}（{len(content)} 字符）",
        path=rel_path,
        bytes_written=len(content.encode()),
    )


async def tool_patch_file(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """应用 unified diff patch 到文件（受 scope_globs 约束，需 confirm=True）。"""
    if not params.get("confirm"):
        return _err("patch_file 需 params.confirm=True 二次确认")
    rel_path = str(params.get("path") or "").strip()
    patch = str(params.get("patch") or "")
    if not rel_path or not patch:
        return _err("缺少 params.path 或 params.patch")
    workspace_root = str(ctx.get("workspace_root") or os.getcwd())
    root = Path(workspace_root).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return _err(f"路径 {rel_path} 越出 workspace_root")
    if not target.is_file():
        return _err(f"目标文件不存在: {rel_path}")
    patch_tmp = root / f".tmp-patch-{os.getpid()}.diff"
    try:
        patch_tmp.write_text(patch, encoding="utf-8")
        check = await _run_cmd(["git", "apply", "--check", str(patch_tmp)], cwd=root, timeout=15)
        if not check.get("ok"):
            return _err(f"patch 校验失败: {check.get('stderr', '')[:500]}")
        apply = await _run_cmd(["git", "apply", str(patch_tmp)], cwd=root, timeout=15)
        if not apply.get("ok"):
            return _err(f"patch 应用失败: {apply.get('stderr', '')[:500]}")
    finally:
        try:
            patch_tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return _ok(f"已应用 patch 到 {rel_path}", path=rel_path)


async def _check_write_gate(
    employee_id: str, tool_name: str, params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
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
        manifest: dict[str, Any] | None = None
        roots: list[str] = []
        try:
            roots = list(mgr.all_mods_roots() or [])
        except Exception:  # noqa: BLE001  降级：用主 mods_root
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
        workspace_root = str(ctx.get("workspace_root") or os.getcwd())
        ws_gate = build_employee_gate(employee_id, manifest, config, workspace_root)
        write_gate = build_write_approval_gate(employee_id, params)
        gate = compose_gates(ws_gate, write_gate)
        if gate is None:
            return {"ok": True}
        return gate(tool_name, params)
    except Exception as exc:  # noqa: BLE001  gate 边界：失败时阻断写操作
        return {"ok": False, "reason": f"gate 检查异常: {exc!r}"}


# ---------------------------------------------------------------------------
# LLM 运维工具（llm-ops-engineer 专属）— 支持 10 家主流 provider
# ---------------------------------------------------------------------------

# Provider 配置 SSOT —— 所有工具从此派生
# 每家 provider 的 key 环境变量、base_url、默认模型、ping 模型、billing endpoint
_PROVIDER_PROFILES: list[dict[str, Any]] = [
    {
        "name": "b.ai",
        "env_keys": ["OPENAI_API_KEY"],
        "base_url_env": "OPENAI_BASE_URL",
        "base_url_default": "https://api.b.ai/v1",
        "model_env": "OPENAI_MODEL",
        "default_model": "MiniMax-M3",
        "ping_model": "MiniMax-M3",
        "billing_endpoints": [
            "/dashboard/billing/credit_grants",
            "/dashboard/billing/subscription",
        ],
        "detect": lambda env: "b.ai" in env.get("OPENAI_BASE_URL", ""),
    },
    {
        "name": "openai",
        "env_keys": ["OPENAI_API_KEY"],
        "base_url_env": "OPENAI_BASE_URL",
        "base_url_default": "https://api.openai.com/v1",
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-4o-mini",
        "ping_model": "gpt-4o-mini",
        "billing_endpoints": ["/dashboard/billing/credit_grants"],
        "detect": lambda env: env.get("OPENAI_BASE_URL", "") in ("", "https://api.openai.com/v1"),
    },
    {
        "name": "deepseek",
        "env_keys": ["DEEPSEEK_API_KEY"],
        "base_url_env": "DEEPSEEK_BASE_URL",
        "base_url_default": "https://api.deepseek.com/v1",
        "model_env": "DEEPSEEK_MODEL",
        "default_model": "deepseek-chat",
        "ping_model": "deepseek-chat",
        "billing_endpoints": ["/user/balance"],
    },
    {
        "name": "qwen",
        "env_keys": ["DASHSCOPE_API_KEY", "QWEN_API_KEY"],
        "base_url_env": "DASHSCOPE_BASE_URL",
        "base_url_default": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_env": "QWEN_MODEL",
        "default_model": "qwen-plus",
        "ping_model": "qwen-turbo",
        "billing_endpoints": [],
    },
    {
        "name": "zhipu",
        "env_keys": ["ZHIPU_API_KEY", "GLM_API_KEY"],
        "base_url_env": "ZHIPU_BASE_URL",
        "base_url_default": "https://open.bigmodel.cn/api/paas/v4",
        "model_env": "GLM_MODEL",
        "default_model": "glm-4-plus",
        "ping_model": "glm-4-flash",
        "billing_endpoints": [],
    },
    {
        "name": "moonshot",
        "env_keys": ["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        "base_url_env": "MOONSHOT_BASE_URL",
        "base_url_default": "https://api.moonshot.cn/v1",
        "model_env": "MOONSHOT_MODEL",
        "default_model": "moonshot-v1-8k",
        "ping_model": "moonshot-v1-8k",
        "billing_endpoints": ["/users/me/balance"],
    },
    {
        "name": "siliconflow",
        "env_keys": ["SILICONFLOW_API_KEY"],
        "base_url_env": "SILICONFLOW_BASE_URL",
        "base_url_default": "https://api.siliconflow.cn/v1",
        "model_env": "SILICONFLOW_MODEL",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "ping_model": "Qwen/Qwen2.5-7B-Instruct",
        "billing_endpoints": ["/user/info"],
    },
    {
        "name": "openrouter",
        "env_keys": ["OPENROUTER_API_KEY"],
        "base_url_env": "OPENROUTER_BASE_URL",
        "base_url_default": "https://openrouter.ai/api/v1",
        "model_env": "OPENROUTER_MODEL",
        "default_model": "openai/gpt-4o-mini",
        "ping_model": "openai/gpt-4o-mini",
        "billing_endpoints": ["/credits"],
    },
    {
        "name": "volcengine",
        "env_keys": ["VOLC_API_KEY", "ARK_API_KEY"],
        "base_url_env": "VOLC_BASE_URL",
        "base_url_default": "https://ark.cn-beijing.volces.com/api/v3",
        "model_env": "VOLC_MODEL",
        "default_model": "doubao-pro-32k",
        "ping_model": "doubao-lite-4k",
        "billing_endpoints": [],
    },
    {
        "name": "ollama",
        "env_keys": [],
        "base_url_env": "OLLAMA_BASE_URL",
        "base_url_default": "http://localhost:11434/v1",
        "model_env": "OLLAMA_MODEL",
        "default_model": "llama3.2",
        "ping_model": "llama3.2",
        "billing_endpoints": ["/api/tags"],
        "no_auth": True,
    },
    {
        # 小米 MiMo (Token Plan, OpenAI 兼容)
        # Key 格式 tp-xxxxx (Token Plan) 与 sk-xxxxx (按量付费) 独立
        # 中国集群 endpoint: token-plan-cn.xiaomimimo.com/v1
        "name": "mimo",
        "env_keys": ["MIMO_API_KEY"],
        "base_url_env": "MIMO_BASE_URL",
        "base_url_default": "https://token-plan-cn.xiaomimimo.com/v1",
        "model_env": "MIMO_MODEL",
        "default_model": "mimo-v2.5-pro",
        "ping_model": "mimo-v2.5-pro",
        "billing_endpoints": [],  # Token Plan 无 billing 查询端点, 订阅期内无限调用
    },
]

# 从 profiles 派生环境变量清单
_LLM_ENV_KEYS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [k for p in _PROVIDER_PROFILES for k in p["env_keys"]]
        + [p["base_url_env"] for p in _PROVIDER_PROFILES if p.get("base_url_env")]
        + [p["model_env"] for p in _PROVIDER_PROFILES if p.get("model_env")]
        + [
            "XCAGI_LLM_PROVIDER",
            "LLM_PROVIDER",
            "LLM_MODE",
            "FHD_LLM_MODE",
            "XCAUTO_API_KEY",
            "XCAUTO_PAT",
            "XIUCI_API_KEY",
            "XCAGI_EMPLOYEE_LLM_MODEL",
        ]
    )
)
# 需要脱敏的 key（含 secret / API_KEY / PAT）
_LLM_SECRET_KEYS: frozenset[str] = frozenset(
    k for k in _LLM_ENV_KEYS if "API_KEY" in k or "PAT" in k or "SECRET" in k
)


def _mask_secret(val: str) -> str:
    """脱敏：sk-abc123xyz → sk-***xyz（保留前 3 + 后 3）。"""
    if not val:
        return ""
    if len(val) <= 8:
        return "***"
    return f"{val[:3]}***{val[-3:]}"


def _read_env_file(env_path: Path) -> dict[str, str]:
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


def _provider_has_key(profile: dict[str, Any], env: dict[str, str]) -> str | None:
    """检查 provider 是否配了 key，返回第一个非空 key（不脱敏）。"""
    for k in profile["env_keys"]:
        v = env.get(k)
        if v:
            return v
    return None


def _provider_base_url(profile: dict[str, Any], env: dict[str, str]) -> str:
    """获取 provider 的 base_url（env 覆盖 default）。"""
    env_key = profile.get("base_url_env")
    if env_key:
        v = env.get(env_key)
        if v:
            return v
    return profile["base_url_default"]


def _provider_model(profile: dict[str, Any], env: dict[str, str]) -> str:
    """获取 provider 的模型（env 覆盖 default）。"""
    env_key = profile.get("model_env")
    if env_key:
        v = env.get(env_key)
        if v:
            return v
    return profile["default_model"]


def _detect_provider_name(profile: dict[str, Any], env: dict[str, str]) -> bool:
    """判断当前环境是否匹配该 provider（用于 OpenAI 兼容的 b.ai/openai 区分）。"""
    detect = profile.get("detect")
    if detect:
        return bool(detect(env))
    # 默认：有 key 就算匹配
    return _provider_has_key(profile, env) is not None


async def tool_read_llm_env_config(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """读取 .env 中 LLM 相关配置（API key 脱敏）。

    真实读取 FHD/.env 文件，提取所有 provider 的配置段，key 一律脱敏为 sk-***xxx。
    """
    env_path = _FHD_ROOT / ".env"
    env_map = _read_env_file(env_path)
    if not env_map:
        return _err(f".env 文件不存在或为空: {env_path}")
    llm_cfg: dict[str, str] = {}
    for k in _LLM_ENV_KEYS:
        if k in env_map:
            v = env_map[k]
            llm_cfg[k] = _mask_secret(v) if k in _LLM_SECRET_KEYS else v
    # 同时读 os.environ（运行时可能被覆盖）
    runtime_cfg: dict[str, str] = {}
    for k in _LLM_ENV_KEYS:
        v = os.environ.get(k)
        if v:
            runtime_cfg[k] = _mask_secret(v) if k in _LLM_SECRET_KEYS else v
    return _ok(
        f".env LLM 段读取完成（{len(llm_cfg)} 项），运行时环境变量 {len(runtime_cfg)} 项",
        env_file=str(env_path),
        env_config=llm_cfg,
        runtime_config=runtime_cfg,
        configured_provider=env_map.get("XCAGI_LLM_PROVIDER")
        or os.environ.get("XCAGI_LLM_PROVIDER")
        or "(未配置)",
        supported_providers=[p["name"] for p in _PROVIDER_PROFILES],
    )


async def tool_list_configured_providers(
    params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """列出当前已配置的 LLM provider 及其状态（支持 10 家）。

    从 os.environ 实时读取，遍历所有 provider profile，标注 key 是否存在。
    """
    env = dict(os.environ)
    providers: list[dict[str, Any]] = []
    for profile in _PROVIDER_PROFILES:
        name = profile["name"]
        key = _provider_has_key(profile, env)
        no_auth = profile.get("no_auth", False)
        # ollama 不需要 key，只要 base_url 可达或默认就列出
        if not key and not no_auth:
            continue
        base_url = _provider_base_url(profile, env)
        model = _provider_model(profile, env)
        entry: dict[str, Any] = {
            "provider": name,
            "api_key": _mask_secret(key) if key else ("(无需)" if no_auth else ""),
            "has_key": bool(key) or no_auth,
            "base_url": base_url,
            "model": model,
            "ping_model": profile["ping_model"],
            "has_billing_api": bool(profile.get("billing_endpoints")),
        }
        providers.append(entry)
    active = os.environ.get("XCAGI_LLM_PROVIDER", "(未配置，走 default path)")
    return _ok(
        f"已配置 {len(providers)} 个 provider（共支持 {len(_PROVIDER_PROFILES)} 家），当前激活: {active}",
        providers=providers,
        active_provider=active,
        employee_llm_model=os.environ.get("XCAGI_EMPLOYEE_LLM_MODEL", "(未配置)"),
        supported_count=len(_PROVIDER_PROFILES),
    )


async def tool_test_llm_key_health(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """对已配置的 provider 发 ping 请求，测延迟和可用性（支持 10 家）。

    真实 HTTP 调用 /chat/completions（max_tokens=1），返回每个 provider 的健康状态。
    可用 params.provider 指定单个 provider，或留空测全部。
    """
    if httpx is None:
        return _err("httpx 未安装，无法测试")
    target = str(params.get("provider") or "").strip().lower()
    env = dict(os.environ)
    results: list[dict[str, Any]] = []

    async def _ping(
        name: str, base_url: str, api_key: str, model: str, no_auth: bool = False
    ) -> dict[str, Any]:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if not no_auth and api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        t0 = asyncio.get_event_loop().time()
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    url,
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
                elapsed = round((asyncio.get_event_loop().time() - t0) * 1000, 1)
                body: Any
                try:
                    body = resp.json()
                except Exception:  # noqa: BLE001
                    body = resp.text[:200]
                return {
                    "provider": name,
                    "ok": resp.is_success,
                    "status": resp.status_code,
                    "latency_ms": elapsed,
                    "model": model,
                    "error": "" if resp.is_success else str(body)[:300],
                }
        except Exception as exc:  # noqa: BLE001  健康检查边界：网络异常转结构化结果
            elapsed = round((asyncio.get_event_loop().time() - t0) * 1000, 1)
            return {
                "provider": name,
                "ok": False,
                "status": 0,
                "latency_ms": elapsed,
                "model": model,
                "error": repr(exc)[:300],
            }

    for profile in _PROVIDER_PROFILES:
        name = profile["name"]
        if target and target != "all" and target != name:
            continue
        key = _provider_has_key(profile, env)
        no_auth = profile.get("no_auth", False)
        if not key and not no_auth:
            continue
        base_url = _provider_base_url(profile, env)
        # ping 用 ping_model（便宜/免费），不是 default_model
        ping_model = profile["ping_model"]
        results.append(await _ping(name, base_url, key or "", ping_model, no_auth))

    if not results:
        return _err(f"未找到已配置 API key 的 provider（已检查 {len(_PROVIDER_PROFILES)} 家）")
    healthy = sum(1 for r in results if r["ok"])
    return _ok(
        f"测试 {len(results)} 个 provider，{healthy} 个健康",
        results=results,
        healthy_count=healthy,
        total_count=len(results),
    )


async def tool_query_provider_usage(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询 provider 账户余额与用量（通用化，支持多家 billing API）。

    真实探测 provider 的 billing endpoint，返回余额/用量。
    可用 params.provider 指定单个 provider，或留空查全部已配置的。
    """
    if httpx is None:
        return _err("httpx 未安装")
    target = str(params.get("provider") or "").strip().lower()
    env = dict(os.environ)
    all_findings: list[dict[str, Any]] = []
    checked = 0
    supported = 0

    async with httpx.AsyncClient(timeout=15) as client:
        for profile in _PROVIDER_PROFILES:
            name = profile["name"]
            if target and target != "all" and target != name:
                continue
            key = _provider_has_key(profile, env)
            no_auth = profile.get("no_auth", False)
            if not key and not no_auth:
                continue
            endpoints = profile.get("billing_endpoints") or []
            if not endpoints:
                all_findings.append(
                    {
                        "provider": name,
                        "endpoint": "(无)",
                        "status": 0,
                        "ok": False,
                        "error": f"{name} 无标准 billing API",
                    }
                )
                continue
            base_url = _provider_base_url(profile, env)
            headers = {}
            if not no_auth and key:
                headers["Authorization"] = f"Bearer {key}"
            checked += 1
            for ep in endpoints:
                url = f"{base_url.rstrip('/')}{ep}"
                try:
                    resp = await client.get(url, headers=headers)
                    body: Any
                    try:
                        body = resp.json()
                    except Exception:  # noqa: BLE001
                        body = resp.text[:300]
                    finding = {
                        "provider": name,
                        "endpoint": ep,
                        "status": resp.status_code,
                        "ok": resp.is_success,
                        "body": body if isinstance(body, (dict, list)) else str(body)[:300],
                    }
                    all_findings.append(finding)
                    if resp.is_success:
                        supported += 1
                except Exception as exc:  # noqa: BLE001
                    all_findings.append(
                        {
                            "provider": name,
                            "endpoint": ep,
                            "status": 0,
                            "ok": False,
                            "error": repr(exc)[:200],
                        }
                    )
    return _ok(
        f"探测 {checked} 个 provider 的 billing endpoint，{supported} 个可用",
        findings=all_findings,
        has_usage_api=supported > 0,
        checked_providers=checked,
        supported_count=supported,
    )


# 内置模型价格表（2026 市场参考价，每 1M tokens，美元）— 覆盖 10 家 provider
_MODEL_PRICES: list[dict[str, Any]] = [
    # DeepSeek
    {
        "model": "DeepSeek-V3",
        "provider": "DeepSeek",
        "input_per_1m": 0.27,
        "output_per_1m": 1.10,
        "context": "64K",
        "note": "国产最便宜之一",
    },
    {
        "model": "DeepSeek-R1",
        "provider": "DeepSeek",
        "input_per_1m": 0.55,
        "output_per_1m": 2.19,
        "context": "64K",
        "note": "推理模型",
    },
    # MiniMax（b.ai）
    {
        "model": "MiniMax-M3",
        "provider": "b.ai",
        "input_per_1m": 0.40,
        "output_per_1m": 1.50,
        "context": "1M",
        "note": "当前在用",
    },
    {
        "model": "MiniMax-Text-01",
        "provider": "MiniMax",
        "input_per_1m": 0.20,
        "output_per_1m": 0.80,
        "context": "1M",
        "note": "便宜",
    },
    # OpenAI
    {
        "model": "gpt-4o",
        "provider": "OpenAI",
        "input_per_1m": 2.50,
        "output_per_1m": 10.00,
        "context": "128K",
        "note": "贵",
    },
    {
        "model": "gpt-4o-mini",
        "provider": "OpenAI",
        "input_per_1m": 0.15,
        "output_per_1m": 0.60,
        "context": "128K",
        "note": "性价比高",
    },
    # Anthropic
    {
        "model": "claude-3.5-sonnet",
        "provider": "Anthropic",
        "input_per_1m": 3.00,
        "output_per_1m": 15.00,
        "context": "200K",
        "note": "最贵",
    },
    # 通义千问
    {
        "model": "qwen-max",
        "provider": "qwen",
        "input_per_1m": 1.40,
        "output_per_1m": 5.60,
        "context": "32K",
        "note": "",
    },
    {
        "model": "qwen-plus",
        "provider": "qwen",
        "input_per_1m": 0.14,
        "output_per_1m": 0.56,
        "context": "128K",
        "note": "便宜",
    },
    {
        "model": "qwen-turbo",
        "provider": "qwen",
        "input_per_1m": 0.05,
        "output_per_1m": 0.20,
        "context": "1M",
        "note": "最便宜之一",
    },
    # 智谱
    {
        "model": "glm-4-plus",
        "provider": "zhipu",
        "input_per_1m": 0.70,
        "output_per_1m": 0.70,
        "context": "128K",
        "note": "",
    },
    {
        "model": "glm-4-flash",
        "provider": "zhipu",
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "context": "128K",
        "note": "免费！",
    },
    # Kimi
    {
        "model": "moonshot-v1-8k",
        "provider": "moonshot",
        "input_per_1m": 1.68,
        "output_per_1m": 1.68,
        "context": "8K",
        "note": "",
    },
    {
        "model": "moonshot-v1-32k",
        "provider": "moonshot",
        "input_per_1m": 3.36,
        "output_per_1m": 3.36,
        "context": "32K",
        "note": "",
    },
    # 硅基流动（聚合，价格按 DeepSeek-V3 估算）
    {
        "model": "deepseek-ai/DeepSeek-V3",
        "provider": "siliconflow",
        "input_per_1m": 0.27,
        "output_per_1m": 1.10,
        "context": "64K",
        "note": "聚合代理",
    },
    {
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "provider": "siliconflow",
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "context": "32K",
        "note": "免费！",
    },
    # OpenRouter（聚合，价格按 OpenAI 估算）
    {
        "model": "openai/gpt-4o-mini",
        "provider": "openrouter",
        "input_per_1m": 0.15,
        "output_per_1m": 0.60,
        "context": "128K",
        "note": "聚合代理",
    },
    # 火山引擎（豆包）
    {
        "model": "doubao-pro-32k",
        "provider": "volcengine",
        "input_per_1m": 0.11,
        "output_per_1m": 0.28,
        "context": "32K",
        "note": "便宜",
    },
    {
        "model": "doubao-lite-4k",
        "provider": "volcengine",
        "input_per_1m": 0.003,
        "output_per_1m": 0.007,
        "context": "4K",
        "note": "极便宜",
    },
    # Ollama（本地，免费）
    {
        "model": "llama3.2",
        "provider": "ollama",
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "context": "128K",
        "note": "本地免费！",
    },
    {
        "model": "qwen2.5:7b",
        "provider": "ollama",
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "context": "32K",
        "note": "本地免费！",
    },
    # 小米 MiMo (Token Plan 订阅制, 订阅期内无限调用, 此处价格按订阅摊销估算)
    {
        "model": "mimo-v2.5-pro",
        "provider": "mimo",
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "context": "128K",
        "note": "Token Plan 订阅期内免费",
    },
]


async def tool_compare_model_prices(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """对比各 LLM 模型价格（内置价格表，覆盖 10 家 provider）。

    支持按 provider 过滤，按价格排序。标注免费模型。
    """
    provider_filter = str(params.get("provider") or "").strip().lower()
    sort_by = str(params.get("sort_by") or "output").strip().lower()
    prices = [dict(p) for p in _MODEL_PRICES]
    if provider_filter:
        prices = [p for p in prices if provider_filter in str(p["provider"]).lower()]
    sort_key = "input_per_1m" if sort_by == "input" else "output_per_1m"
    prices.sort(key=lambda x: float(x.get(sort_key, 999)))
    free_models = [
        p["model"]
        for p in prices
        if float(p.get("input_per_1m", 0)) == 0 and float(p.get("output_per_1m", 0)) == 0
    ]
    cheapest = prices[0] if prices else None
    return _ok(
        f"对比 {len(prices)} 个模型（按 {sort_key} 升序），{len(free_models)} 个免费",
        prices=prices,
        free_models=free_models,
        cheapest=cheapest,
        sort_by=sort_key,
        total_models=len(_MODEL_PRICES),
        providers_covered=sorted({p["provider"] for p in _MODEL_PRICES}),
    )


async def tool_query_local_token_usage(
    params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """查询本地 token 用量账本（真实数据，非 LLM 编造）。

    读取 FHD 的 model_usage_ledger.json，返回 token 用量统计。
    b.ai/mimo 等平台不开放 usage 查询 API，但 FHD 在 agent_orchestrator
    路径下会记录每次 LLM 调用的 prompt/completion/total tokens 到本地账本。

    可用 params:
    - user_id: 按用户筛选
    - run_id: 按会话/run 筛选
    - limit: 返回最近 N 条明细（默认 20，0 = 只返回汇总不返回明细）
    - group_by: "model" | "provider" | "none"（默认 model）
    """
    try:
        from app.infrastructure.billing.model_usage import (
            list_model_usage_entries,
            model_usage_ledger_path,
        )
    except ImportError as exc:
        return _err(f"无法导入 billing 模块: {exc}")

    user_id = str(params.get("user_id") or "").strip()
    run_id = str(params.get("run_id") or "").strip()
    limit = int(params.get("limit") if params.get("limit") is not None else 20)
    group_by = str(params.get("group_by") or "model").strip().lower()

    ledger_path = model_usage_ledger_path()
    entries = list_model_usage_entries(
        limit=max(limit, 500) if limit > 0 else 500, run_id=run_id, user_id=user_id
    )

    # 只统计 model_call 类型（tool_call 的 token 是 0）
    model_entries = [e for e in entries if str(e.get("entry_type") or "model_call") == "model_call"]

    # 汇总
    total_prompt = sum(int(e.get("prompt_tokens") or 0) for e in model_entries)
    total_completion = sum(int(e.get("completion_tokens") or 0) for e in model_entries)
    total_tokens = sum(int(e.get("total_tokens") or 0) for e in model_entries)
    total_cost = sum(int(e.get("cost_units") or 0) for e in model_entries)

    # 分组统计
    groups: dict[str, dict[str, Any]] = {}
    group_key = "model" if group_by == "model" else ("provider" if group_by == "provider" else "")
    for e in model_entries:
        if not group_key:
            continue
        key = str(e.get(group_key) or "unknown")
        g = groups.setdefault(
            key,
            {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_units": 0,
                "calls": 0,
            },
        )
        g["prompt_tokens"] += int(e.get("prompt_tokens") or 0)
        g["completion_tokens"] += int(e.get("completion_tokens") or 0)
        g["total_tokens"] += int(e.get("total_tokens") or 0)
        g["cost_units"] += int(e.get("cost_units") or 0)
        g["calls"] += 1

    # 明细（限制条数）
    details = []
    if limit > 0:
        for e in model_entries[:limit]:
            details.append(
                {
                    "created_at": e.get("created_at", ""),
                    "provider": e.get("provider", ""),
                    "model": e.get("model", ""),
                    "prompt_tokens": int(e.get("prompt_tokens") or 0),
                    "completion_tokens": int(e.get("completion_tokens") or 0),
                    "total_tokens": int(e.get("total_tokens") or 0),
                    "cost_units": int(e.get("cost_units") or 0),
                    "run_id": e.get("run_id", ""),
                    "user_id": e.get("user_id", ""),
                }
            )

    # 账本是否存在
    ledger_exists = ledger_path.is_file()

    return _ok(
        f"本地账本 {len(model_entries)} 条 model_call 记录，总 token={total_tokens:,}",
        ledger_path=str(ledger_path),
        ledger_exists=ledger_exists,
        usage_summary={
            "total_calls": len(model_entries),
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "cost_units": total_cost,
        },
        groups=groups if group_key else {},
        group_by=group_by,
        details=details,
        detail_count=len(details),
        note="仅 agent_orchestrator 路径记录；conversation 服务主路径未持久化。b.ai/mimo 平台不开放 usage API，需去各自控制台查看。",
    )


async def tool_query_cursor_usage(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询 Cursor 编辑器的使用统计（自动采集，含精确 token 用量）。

    数据源（按精确度从高到低）：
    1. cursor-usage CLI → 调 Cursor Dashboard 内部 API，返回精确的
       inputTokens/outputTokens/cacheReadTokens/totalCents（按 model 分组）
    2. macOS Keychain cursor-access-token → api2.cursor.sh/auth/usage
       获取免费配额（gpt-4）的请求次数
    3. 本地 ~/.cursor/ai-tracking/ai-code-tracking.db（SQLite）
       获取 AI 代码生成次数和 commit 代码比例

    可用 params:
    - days: 统计最近 N 天的数据（默认 30，0 = 当前账单月）
    - detail_limit: 返回最近 N 条明细事件（默认 10，0 = 不返回明细）
    """
    import csv
    import io
    import shutil
    import sqlite3
    import subprocess
    from datetime import UTC, datetime, timedelta

    days = int(params.get("days") if params.get("days") is not None else 30)
    detail_limit = int(params.get("detail_limit") if params.get("detail_limit") is not None else 10)
    result_data: dict[str, Any] = {
        "sources": [],
        "cli_usage": None,
        "api_usage": None,
        "local_db": None,
        "cursor_summary": {},
    }

    # --- 数据源 1：cursor-usage CLI（精确 token + 费用）---
    cli_bin = shutil.which("cursor-usage") or str(
        Path.home() / "Library" / "Python" / "3.9" / "bin" / "cursor-usage"
    )
    if Path(cli_bin).is_file():
        result_data["sources"].append("cursor-usage-cli")
        try:
            # 获取汇总 JSON
            cmd = [cli_bin, "--json"]
            if days > 0:
                cmd.extend(["--days", str(days)])
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0 and proc.stdout.strip():
                raw = json.loads(proc.stdout)
                aggregations = raw.get("aggregations", [])
                # 汇总
                total_input = 0
                total_output = 0
                total_cache_read = 0
                total_cache_write = 0
                total_cents = 0.0
                by_model = []
                for agg in aggregations:
                    inp = int(agg.get("inputTokens") or 0)
                    out = int(agg.get("outputTokens") or 0)
                    cr = int(agg.get("cacheReadTokens") or 0)
                    cw = int(agg.get("cacheWriteTokens") or 0)
                    cents = float(agg.get("totalCents") or 0)
                    total_input += inp
                    total_output += out
                    total_cache_read += cr
                    total_cache_write += cw
                    total_cents += cents
                    by_model.append(
                        {
                            "model": agg.get("modelIntent", "unknown"),
                            "input_tokens": inp,
                            "output_tokens": out,
                            "cache_read_tokens": cr,
                            "cache_write_tokens": cw,
                            "total_tokens": inp + out + cr + cw,
                            "cost_cents": round(cents, 2),
                            "cost_usd": round(cents / 100, 4),
                            "tier": agg.get("tier"),
                        }
                    )
                by_model.sort(key=lambda x: x["cost_cents"], reverse=True)
                result_data["cli_usage"] = {
                    "total_input_tokens": total_input,
                    "total_output_tokens": total_output,
                    "total_cache_read_tokens": total_cache_read,
                    "total_cache_write_tokens": total_cache_write,
                    "total_tokens": total_input
                    + total_output
                    + total_cache_read
                    + total_cache_write,
                    "total_cost_cents": round(total_cents, 2),
                    "total_cost_usd": round(total_cents / 100, 2),
                    "by_model": by_model,
                    "model_count": len(by_model),
                    "days_filter": days if days > 0 else "current_billing_month",
                }

                # 可选：获取明细 CSV
                if detail_limit > 0:
                    csv_cmd = [cli_bin]
                    if days > 0:
                        csv_cmd.extend(["--days", str(days)])
                    else:
                        csv_cmd.extend(["--month", datetime.now(UTC).strftime("%Y-%m")])
                    csv_cmd.extend(["--csv", "-"])
                    csv_proc = subprocess.run(csv_cmd, capture_output=True, text=True, timeout=60)
                    if csv_proc.returncode == 0 and csv_proc.stdout:
                        reader = csv.DictReader(io.StringIO(csv_proc.stdout))
                        events = list(reader)
                        # 取最近 detail_limit 条
                        events = events[-detail_limit:] if len(events) > detail_limit else events
                        result_data["cli_usage"]["recent_events"] = [
                            {
                                "datetime": e.get("datetime_local", ""),
                                "model": e.get("model", ""),
                                "input_tokens": int(e.get("input_tokens") or 0),
                                "output_tokens": int(e.get("output_tokens") or 0),
                                "cache_read_tokens": int(e.get("cache_read_tokens") or 0),
                                "value_cents": float(e.get("value_cents") or 0),
                                "kind": e.get("kind", ""),
                            }
                            for e in events
                        ]
                        result_data["cli_usage"]["total_events"] = len(
                            list(csv.DictReader(io.StringIO(csv_proc.stdout)))
                        )
        except Exception as exc:  # noqa: BLE001
            result_data["cli_usage"] = {"error": str(exc)}

    # --- 数据源 2：Cursor API（/auth/usage，免费配额）---
    api_token = ""
    try:
        proc = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                "cursor-access-token",
                "-a",
                "cursor-user",
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            api_token = proc.stdout.strip()
    except Exception:  # noqa: BLE001
        pass

    if api_token:
        result_data["sources"].append("cursor-api:auth/usage")
        try:
            import httpx as _httpx

            resp = _httpx.get(
                "https://api2.cursor.sh/auth/usage",
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "User-Agent": "cursor/0.50.0",
                    "x-cursor-client-version": "0.50.0",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                api_data = resp.json()
                result_data["api_usage"] = {
                    "free_quota": api_data,
                    "start_of_month": api_data.get("startOfMonth", ""),
                    "note": "仅返回免费配额(gpt-4)；Pro 版用量由 cursor-usage CLI 提供",
                }
        except Exception as exc:  # noqa: BLE001
            result_data["api_usage"] = {"error": str(exc)}

    # --- 数据源 3：本地 ai-code-tracking.db（AI 代码生成次数 + commit 比例）---
    db_path = Path.home() / ".cursor" / "ai-tracking" / "ai-code-tracking.db"
    if db_path.is_file():
        result_data["sources"].append(f"local-db:{db_path.name}")
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            since_ts = 0
            if days > 0:
                since_dt = datetime.now(UTC) - timedelta(days=days)
                since_ts = int(since_dt.timestamp() * 1000)

            if since_ts > 0:
                cur.execute(
                    "SELECT model, COUNT(*) as count FROM ai_code_hashes WHERE timestamp >= ? GROUP BY model ORDER BY count DESC",
                    (since_ts,),
                )
            else:
                cur.execute(
                    "SELECT model, COUNT(*) as count FROM ai_code_hashes GROUP BY model ORDER BY count DESC",
                )
            model_counts = [
                {"model": r["model"] or "(unknown)", "count": r["count"]} for r in cur.fetchall()
            ]

            cur.execute("SELECT COUNT(*) FROM ai_code_hashes")
            total_hashes = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) as commits, SUM(linesAdded) as total_add, SUM(tabLinesAdded) as tab_add, SUM(composerLinesAdded) as comp_add, SUM(humanLinesAdded) as human_add FROM scored_commits"
            )
            row = cur.fetchone()
            commits_data = {
                "total_commits": row["commits"],
                "total_lines_added": row["total_add"] or 0,
                "tab_lines_added": row["tab_add"] or 0,
                "composer_lines_added": row["comp_add"] or 0,
                "human_lines_added": row["human_add"] or 0,
            }
            ai_lines = commits_data["tab_lines_added"] + commits_data["composer_lines_added"]
            total_lines = commits_data["total_lines_added"] or 1
            commits_data["ai_percentage"] = round(ai_lines / total_lines * 100, 1)

            conn.close()

            result_data["local_db"] = {
                "db_path": str(db_path),
                "total_ai_generations": total_hashes,
                "by_model": model_counts,
                "commits": commits_data,
                "days_filter": days if days > 0 else "all",
            }
        except Exception as exc:  # noqa: BLE001
            result_data["local_db"] = {"error": str(exc)}

    # --- 汇总 ---
    cli = result_data.get("cli_usage") or {}
    total_tokens = cli.get("total_tokens", 0)
    total_cost = cli.get("total_cost_usd", 0)
    total_gen = 0
    if result_data.get("local_db") and "error" not in result_data["local_db"]:
        total_gen = result_data["local_db"].get("total_ai_generations", 0)
    result_data["cursor_summary"] = {
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
        "total_ai_generations": total_gen,
        "has_cli": bool(cli and "error" not in cli),
        "has_api_token": bool(api_token),
        "has_local_db": bool(
            result_data.get("local_db") and "error" not in result_data.get("local_db", {})
        ),
        "note": "cursor-usage CLI 提供精确 token 和费用（来自 Dashboard API）。本地 DB 提供 AI 生成次数和代码比例。",
    }

    return _ok(
        f"Cursor 使用统计：{total_tokens:,} tokens，${total_cost}，{total_gen} 次 AI 生成，{len(result_data['sources'])} 个数据源",
        **result_data,
    )


async def tool_query_codex_usage(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询 OpenAI Codex CLI 的使用统计（自动从本地数据采集）。

    数据源：
    1. ~/.codex/archived_sessions/*.jsonl — 逐会话的精确 token 用量
       （input/cached/output/reasoning/total tokens + rate_limits）
    2. ~/.codex/goals_1.sqlite 的 thread_goals 表 — 按会话的 tokens_used 和状态
    3. ~/.codex/config.toml — 当前 model 配置

    可用 params:
    - days: 统计最近 N 天的数据（默认 30，0 = 全部）
    """
    import glob
    import sqlite3
    from datetime import UTC, datetime, timedelta

    days = int(params.get("days") if params.get("days") is not None else 30)
    codex_dir = Path.home() / ".codex"
    result_data: dict[str, Any] = {
        "sources": [],
        "sessions": None,
        "goals_db": None,
        "config": None,
        "codex_summary": {},
    }

    # --- 数据源 1：archived_sessions/*.jsonl ---
    sessions_dir = codex_dir / "archived_sessions"
    jsonl_files = sorted(glob.glob(str(sessions_dir / "*.jsonl"))) if sessions_dir.is_dir() else []
    if jsonl_files:
        result_data["sources"].append(f"archived-sessions:{len(jsonl_files)}-files")
        try:
            since_dt = None
            if days > 0:
                since_dt = datetime.now(UTC) - timedelta(days=days)

            sessions_list = []
            total_input = 0
            total_cached = 0
            total_output = 0
            total_reasoning = 0
            total_tokens = 0

            for fpath in jsonl_files:
                session_model = "unknown"
                session_cwd = ""
                session_ts = ""
                last_usage = None
                rate_limit_used = None

                with open(fpath, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            evt = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        evt_type = evt.get("type", "")
                        payload = evt.get("payload", {})

                        if evt_type == "session_meta":
                            session_model = payload.get("model", session_model)
                            session_cwd = payload.get("cwd", "")
                            session_ts = payload.get("timestamp", "")

                        if evt_type == "event_msg" and payload.get("type") == "token_count":
                            info = payload.get("info", {})
                            last_usage = info.get("total_token_usage", {})
                            rl = payload.get("rate_limits", {})
                            primary = rl.get("primary", {})
                            rate_limit_used = primary.get("used_percent")

                if last_usage:
                    inp = int(last_usage.get("input_tokens") or 0)
                    cached = int(last_usage.get("cached_input_tokens") or 0)
                    out = int(last_usage.get("output_tokens") or 0)
                    reasoning = int(last_usage.get("reasoning_output_tokens") or 0)
                    tot = int(last_usage.get("total_tokens") or 0)

                    # 日期过滤
                    if since_dt and session_ts:
                        try:
                            evt_dt = datetime.fromisoformat(session_ts.replace("Z", "+00:00"))
                            if evt_dt < since_dt:
                                continue
                        except (ValueError, TypeError):
                            pass

                    total_input += inp
                    total_cached += cached
                    total_output += out
                    total_reasoning += reasoning
                    total_tokens += tot

                    sessions_list.append(
                        {
                            "file": Path(fpath).name,
                            "model": session_model,
                            "cwd": session_cwd,
                            "timestamp": session_ts,
                            "input_tokens": inp,
                            "cached_input_tokens": cached,
                            "output_tokens": out,
                            "reasoning_output_tokens": reasoning,
                            "total_tokens": tot,
                            "rate_limit_used_percent": rate_limit_used,
                        }
                    )

            sessions_list.sort(key=lambda x: x["timestamp"], reverse=True)
            result_data["sessions"] = {
                "total_sessions": len(sessions_list),
                "total_input_tokens": total_input,
                "total_cached_input_tokens": total_cached,
                "total_output_tokens": total_output,
                "total_reasoning_output_tokens": total_reasoning,
                "total_tokens": total_tokens,
                "by_session": sessions_list[:20],
                "days_filter": days if days > 0 else "all",
            }
        except Exception as exc:  # noqa: BLE001
            result_data["sessions"] = {"error": str(exc)}

    # --- 数据源 2：goals_1.sqlite ---
    goals_db = codex_dir / "goals_1.sqlite"
    if goals_db.is_file():
        result_data["sources"].append("goals-sqlite")
        try:
            conn = sqlite3.connect(str(goals_db))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT thread_id, objective, status, token_budget, tokens_used, time_used_seconds, created_at_ms FROM thread_goals ORDER BY created_at_ms DESC"
            )
            goals_list = []
            total_goal_tokens = 0
            total_goal_time = 0
            for r in cur.fetchall():
                tokens = r["tokens_used"] or 0
                total_goal_tokens += tokens
                total_goal_time += r["time_used_seconds"] or 0
                goals_list.append(
                    {
                        "thread_id": r["thread_id"],
                        "objective": (r["objective"] or "")[:80],
                        "status": r["status"],
                        "token_budget": r["token_budget"],
                        "tokens_used": tokens,
                        "time_used_seconds": r["time_used_seconds"] or 0,
                        "created_at": datetime.fromtimestamp(
                            (r["created_at_ms"] or 0) / 1000
                        ).strftime("%Y-%m-%d %H:%M"),
                    }
                )
            conn.close()
            result_data["goals_db"] = {
                "total_threads": len(goals_list),
                "total_tokens_used": total_goal_tokens,
                "total_time_seconds": total_goal_time,
                "by_status": {
                    s: sum(1 for g in goals_list if g["status"] == s)
                    for s in {g["status"] for g in goals_list}
                },
                "threads": goals_list,
            }
        except Exception as exc:  # noqa: BLE001
            result_data["goals_db"] = {"error": str(exc)}

    # --- 数据源 3：config.toml ---
    config_file = codex_dir / "config.toml"
    if config_file.is_file():
        result_data["sources"].append("config-toml")
        try:
            config_text = config_file.read_text(encoding="utf-8")
            model = ""
            reasoning_effort = ""
            for line in config_text.splitlines():
                line = line.strip()
                if line.startswith("model") and "=" in line:
                    model = line.split("=", 1)[1].strip().strip('"')
                if line.startswith("model_reasoning_effort") and "=" in line:
                    reasoning_effort = line.split("=", 1)[1].strip().strip('"')
            result_data["config"] = {
                "model": model,
                "reasoning_effort": reasoning_effort,
            }
        except Exception as exc:  # noqa: BLE001
            result_data["config"] = {"error": str(exc)}

    # --- 汇总 ---
    sess = result_data.get("sessions") or {}
    goals = result_data.get("goals_db") or {}
    total_tok = sess.get("total_tokens", 0) or goals.get("total_tokens_used", 0)
    result_data["codex_summary"] = {
        "total_tokens": total_tok,
        "total_sessions": sess.get("total_sessions", 0),
        "total_threads": goals.get("total_threads", 0),
        "total_time_seconds": goals.get("total_time_seconds", 0),
        "model": (result_data.get("config") or {}).get("model", "unknown"),
        "note": "Codex CLI 本地数据。archived_sessions 含精确 token（input/cached/output/reasoning），goals_db 含按会话的 token 和状态。",
    }

    return _ok(
        f"Codex 使用统计：{total_tok:,} tokens，{sess.get('total_sessions', 0)} 个会话，{len(result_data['sources'])} 个数据源",
        **result_data,
    )


async def tool_query_trae_usage(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询 Trae IDE 的使用统计（自动从本地数据采集）。

    数据源：
    1. ~/.trae-cn/trae-jwt-token → 尝试调 Trae API 获取 token 用量
    2. Trae CN/User/globalStorage/state.vscdb — 聊天轮次、模型列表、用户 ID
    3. ~/.trae-cn/ 目录 — 配置文件

    注意：Trae 的 token 用量 API 被 403 拦截（需要网页 cookie），
    本工具能提取聊天轮次、模型列表、当前模型等本地数据。
    """
    import sqlite3

    trae_cn = Path.home() / ".trae-cn"
    trae_app = Path.home() / "Library" / "Application Support" / "Trae CN"
    result_data: dict[str, Any] = {
        "sources": [],
        "api_usage": None,
        "local_state": None,
        "config": None,
        "trae_summary": {},
    }

    # --- 数据源 1：尝试调 Trae API ---
    jwt_path = trae_cn / "trae-jwt-token"
    if jwt_path.is_file():
        result_data["sources"].append("trae-jwt-token")
        jwt_token = jwt_path.read_text(encoding="utf-8").strip()
        try:
            import httpx as _httpx

            resp = _httpx.get(
                "https://trae.cn/api/v1/user/usage",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "User-Agent": "Trae/1.10.0",
                    "Content-Type": "application/json",
                },
                timeout=8,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                result_data["api_usage"] = resp.json()
            else:
                result_data["api_usage"] = {
                    "status_code": resp.status_code,
                    "note": f"Trae API 返回 {resp.status_code}，token 用量需去 Trae 网页设置页查看",
                }
        except Exception as exc:  # noqa: BLE001
            result_data["api_usage"] = {"error": str(exc)}

    # --- 数据源 2：state.vscdb ---
    state_db = trae_app / "User" / "globalStorage" / "state.vscdb"
    if state_db.is_file():
        result_data["sources"].append("state.vscdb")
        try:
            conn = sqlite3.connect(str(state_db))
            cur = conn.cursor()

            # 聊天轮次统计
            cur.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'ai.chat.feedback%'")
            feedback = {}
            for k, v in cur.fetchall():
                feedback[k] = v
            accumulated_turns = 0
            for k, v in feedback.items():
                if "accumulatedTurns" in k:
                    try:
                        accumulated_turns = int(v)
                    except (ValueError, TypeError):
                        pass

            # 当前选择的模型
            cur.execute(
                "SELECT key, value FROM ItemTable WHERE key LIKE '%sessionRelation:globalModelMap%'"
            )
            current_models = {}
            for _k, v in cur.fetchall():
                try:
                    current_models = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    pass

            # 可用模型列表
            cur.execute("SELECT value FROM ItemTable WHERE key LIKE '%model_list_map%' LIMIT 1")
            row = cur.fetchone()
            available_models = {}
            if row:
                try:
                    available_models = json.loads(row[0])
                except (json.JSONDecodeError, TypeError):
                    pass

            # 用户 ID
            cur.execute(
                "SELECT key FROM ItemTable WHERE key LIKE '%_ai-chat:sessionRelation%' LIMIT 1"
            )
            user_id = ""
            row = cur.fetchone()
            if row and "_" in row[0]:
                user_id = row[0].split("_")[0]

            conn.close()

            result_data["local_state"] = {
                "user_id": user_id,
                "accumulated_chat_turns": accumulated_turns,
                "current_models": current_models,
                "available_models_by_mode": {
                    mode: [m.get("name", "") for m in models if isinstance(m, dict)]
                    for mode, models in available_models.items()
                },
                "feedback_keys": list(feedback.keys()),
            }
        except Exception as exc:  # noqa: BLE001
            result_data["local_state"] = {"error": str(exc)}

    # --- 数据源 3：配置文件 ---
    argv_file = trae_cn / "argv.json"
    if argv_file.is_file():
        result_data["sources"].append("argv.json")
        try:
            result_data["config"] = {"argv": json.loads(argv_file.read_text(encoding="utf-8"))}
        except Exception:  # noqa: BLE001
            pass

    # --- 汇总 ---
    local = result_data.get("local_state") or {}
    result_data["trae_summary"] = {
        "chat_turns": local.get("accumulated_chat_turns", 0),
        "current_models": local.get("current_models", {}),
        "user_id": local.get("user_id", ""),
        "api_accessible": bool(
            result_data.get("api_usage")
            and isinstance(result_data.get("api_usage"), dict)
            and "status_code" not in result_data.get("api_usage", {})
        ),
        "note": "Trae token 用量 API 被 403 拦截。本地能提取聊天轮次和模型列表，精确 token 用量需去 Trae 设置页查看。",
    }

    return _ok(
        f"Trae 使用统计：{local.get('accumulated_chat_turns', 0)} 轮聊天，{len(result_data['sources'])} 个数据源",
        **result_data,
    )


# ---------------------------------------------------------------------------
# 工具注册表
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Any] = {
    # quality
    "run_pytest": tool_run_pytest,
    "run_ruff_check": tool_run_ruff_check,
    "run_ruff_format": tool_run_ruff_format,
    "run_mypy": tool_run_mypy,
    "check_coverage": tool_check_coverage,
    "count_type_debt": tool_count_type_debt,
    "count_raw_sql": tool_count_raw_sql,
    "run_arch_fitness": tool_run_arch_fitness,
    "verify_version_anchors": tool_verify_version_anchors,
    "verify_employee_contract": tool_verify_employee_contract,
    "mutation_kill_report": tool_mutation_kill_report,
    # git
    "git_status": tool_git_status,
    "git_log": tool_git_log,
    "git_diff": tool_git_diff,
    "git_branch": tool_git_branch,
    # deploy
    "pack_release": tool_pack_release,
    "list_deploy_scripts": tool_list_deploy_scripts,
    "trigger_gh_workflow": tool_trigger_gh_workflow,
    # infra
    "nginx_test": tool_nginx_test,
    "api_health": tool_api_health,
    "mod_loading_status": tool_mod_loading_status,
    "disk_usage": tool_disk_usage,
    "tail_logs": tool_tail_logs,
    "performance_status": tool_performance_status,
    # mod
    "list_mods": tool_list_mods,
    "list_employee_packs": tool_list_employee_packs,
    "validate_employee_pack": tool_validate_employee_pack,
    "duty_graph_health": tool_duty_graph_health,
    # doc
    "list_docs": tool_list_docs,
    "read_file": tool_read_file,
    "list_scripts": tool_list_scripts,
    # platform
    "list_employees": tool_list_employees,
    "employee_status": tool_employee_status,
    "list_action_items": tool_list_action_items,
    "employee_autonomy_dashboard": tool_employee_autonomy_dashboard,
    # craft
    "list_workbench_sessions": tool_list_workbench_sessions,
    "sandbox_python": tool_sandbox_python,
    # payment
    "check_transactions": tool_check_transactions,
    "list_invoices": tool_list_invoices,
    # ecosystem
    "list_enterprise_mods": tool_list_enterprise_mods,
    "list_users": tool_list_users,
    # frontend
    "frontend_lint": tool_frontend_lint,
    "frontend_typecheck": tool_frontend_typecheck,
    "frontend_test": tool_frontend_test,
    # mobile
    "android_gradle_build": tool_android_gradle_build,
    # code-write（受 scope_globs + write_approval gate 约束）
    "patch_file": tool_patch_file,
    "write_file": tool_write_file,
    # llm-ops（llm-ops-engineer 专属，支持 11 家 provider）
    "read_llm_env_config": tool_read_llm_env_config,
    "list_configured_providers": tool_list_configured_providers,
    "test_llm_key_health": tool_test_llm_key_health,
    "query_provider_usage": tool_query_provider_usage,
    "compare_model_prices": tool_compare_model_prices,
    "query_local_token_usage": tool_query_local_token_usage,
    "query_cursor_usage": tool_query_cursor_usage,
    "query_codex_usage": tool_query_codex_usage,
    "query_trae_usage": tool_query_trae_usage,
}


# ---------------------------------------------------------------------------
# 52 个编制员工的专属工具注册
# ---------------------------------------------------------------------------

EMPLOYEE_TOOLS: dict[str, list[str]] = {
    # --- site-and-marketing ---
    "site-content-editor": ["read_file", "list_docs", "git_status", "git_diff"],
    "seo-sitemap-curator": ["read_file", "list_docs", "api_health", "git_status"],
    "marketing-site-builder": ["list_docs", "read_file", "list_scripts", "git_status"],
    "flask-entry-keeper": ["read_file", "api_health", "git_diff", "run_ruff_check"],
    # --- modstore-frontend ---
    "market-frontend-dev": ["frontend_lint", "frontend_typecheck", "frontend_test", "git_diff"],
    "workbench-ux-stylist": ["frontend_lint", "frontend_test", "read_file", "list_docs"],
    # --- platform-core ---
    "user-customer-service-officer": [
        "list_employees",
        "employee_status",
        "list_action_items",
        "list_users",
    ],
    "intake-dispatcher": ["list_employees", "list_workbench_sessions", "list_action_items"],
    "fhd-core-maintainer": [
        "run_pytest",
        "run_ruff_check",
        "run_mypy",
        "check_coverage",
        "count_type_debt",
        "count_raw_sql",
        "verify_version_anchors",
        "git_diff",
        "patch_file",
        "write_file",
    ],
    "vibe-coding-maintainer": [
        "run_pytest",
        "run_ruff_check",
        "git_status",
        "git_diff",
        "read_file",
    ],
    "mods-and-eskill-curator": [
        "list_mods",
        "list_employee_packs",
        "validate_employee_pack",
        "mod_loading_status",
    ],
    "change-request-auditor": [
        "git_diff",
        "git_log",
        "run_ruff_check",
        "run_mypy",
        "verify_employee_contract",
    ],
    "daily-orchestrator": [
        "list_employees",
        "employee_status",
        "duty_graph_health",
        "list_action_items",
        "employee_autonomy_dashboard",
    ],
    "task-router-officer": ["list_employees", "employee_status", "list_action_items"],
    "enterprise-adoption-officer": ["list_users", "list_enterprise_mods", "list_mods"],
    "delivery-receipt-officer": ["git_log", "git_status", "list_action_items", "api_health"],
    "mobile-android-release-officer": [
        "android_gradle_build",
        "git_status",
        "git_log",
        "list_scripts",
    ],
    "mobile-ios-release-officer": ["git_status", "git_log", "list_scripts", "read_file"],
    # --- modstore-backend ---
    "modstore-backend-api": [
        "api_health",
        "run_pytest",
        "run_ruff_check",
        "git_diff",
        "performance_status",
    ],
    "employee-pack-curator": [
        "list_employee_packs",
        "validate_employee_pack",
        "list_mods",
        "verify_employee_contract",
    ],
    "java-payment-bridge-officer": [
        "api_health",
        "check_transactions",
        "list_invoices",
        "read_file",
    ],
    "payment-billing-reconciler": [
        "check_transactions",
        "list_invoices",
        "list_users",
        "read_file",
    ],
    # --- server-and-ops ---
    "nginx-config-engineer": ["nginx_test", "api_health", "read_file", "git_diff"],
    "push-update-context-officer": ["list_deploy_scripts", "git_log", "api_health", "read_file"],
    "deploy-release-officer": [
        "pack_release",
        "list_deploy_scripts",
        "trigger_gh_workflow",
        "git_status",
        "git_log",
        "api_health",
    ],
    "security-secrets-guard": ["git_diff", "read_file", "list_scripts", "git_status"],
    "log-monitor-incident": ["tail_logs", "api_health", "performance_status", "disk_usage"],
    "retention-officer": ["disk_usage", "tail_logs", "list_scripts", "git_status"],
    "dbops-engineer": ["api_health", "performance_status", "read_file", "tail_logs"],
    "legacy-archive-curator": ["disk_usage", "list_scripts", "git_status", "read_file"],
    "llm-ops-engineer": [
        "read_llm_env_config",
        "list_configured_providers",
        "test_llm_key_health",
        "query_provider_usage",
        "compare_model_prices",
        "query_local_token_usage",
        "query_cursor_usage",
        "query_codex_usage",
        "query_trae_usage",
    ],
    # --- quality-and-docs ---
    "test-qa-runner": [
        "run_pytest",
        "run_ruff_check",
        "run_ruff_format",
        "run_mypy",
        "check_coverage",
        "run_arch_fitness",
        "frontend_test",
    ],
    "doc-knowledge-curator": ["list_docs", "read_file", "verify_version_anchors", "git_status"],
    "employee-interview-assistant": [
        "list_employees",
        "list_employee_packs",
        "validate_employee_pack",
        "employee_status",
    ],
    "employee-pack-quality-interviewer": [
        "validate_employee_pack",
        "list_employee_packs",
        "verify_employee_contract",
        "list_mods",
    ],
    # --- craft-workshop ---
    "intent-analyst": ["list_workbench_sessions", "list_employees", "list_action_items"],
    "employee-planner": ["list_employees", "list_workbench_sessions", "read_file", "list_docs"],
    "artifact-generator": ["sandbox_python", "read_file", "list_scripts", "git_diff"],
    "quality-validator": [
        "run_ruff_check",
        "run_mypy",
        "run_arch_fitness",
        "verify_employee_contract",
    ],
    "miniapp-builder": ["frontend_lint", "frontend_typecheck", "list_scripts", "read_file"],
    "script-binder": ["read_file", "list_scripts", "sandbox_python", "git_diff"],
    "workflow-automator": ["list_scripts", "read_file", "api_health", "list_action_items"],
    "pack-registrar": ["list_employee_packs", "validate_employee_pack", "list_mods", "git_status"],
    "sandbox-tester": ["sandbox_python", "run_pytest", "frontend_test", "read_file"],
    "code-validator": ["run_ruff_check", "run_ruff_format", "run_mypy", "run_arch_fitness"],
    "self-checker": ["run_pytest", "run_ruff_check", "verify_version_anchors", "check_coverage"],
    "host-checker": [
        "api_health",
        "disk_usage",
        "nginx_test",
        "mod_loading_status",
        "performance_status",
    ],
    "hex-quality-assessor": [
        "run_pytest",
        "run_ruff_check",
        "run_mypy",
        "check_coverage",
        "count_type_debt",
        "count_raw_sql",
        "run_arch_fitness",
        "mutation_kill_report",
    ],
    # --- partner-ecosystem ---
    "ecosystem-partner-onboard-officer": [
        "list_users",
        "list_enterprise_mods",
        "list_mods",
        "list_action_items",
    ],
    "ecosystem-joint-catalog-officer": [
        "list_mods",
        "list_enterprise_mods",
        "list_employee_packs",
        "validate_employee_pack",
    ],
    "ecosystem-delivery-reporter": ["git_log", "list_action_items", "api_health", "list_employees"],
    "ecosystem-investor-portal-officer": [
        "list_users",
        "list_invoices",
        "check_transactions",
        "api_health",
    ],
    "ecosystem-revenue-share-reconciler": [
        "check_transactions",
        "list_invoices",
        "list_users",
        "read_file",
    ],
}


def get_employee_tools(employee_id: str) -> list[str]:
    """返回某员工注册的专属工具名列表。"""
    return list(EMPLOYEE_TOOLS.get(employee_id, []))


def list_all_tool_names() -> list[str]:
    """返回全部已注册工具名。"""
    return sorted(TOOL_REGISTRY.keys())


# ---------------------------------------------------------------------------
# 专属工具调度入口（executor 拦截 specialized handler 时调用）
# ---------------------------------------------------------------------------


async def handle_specialized(
    employee_id: str, payload: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """专属工具调度入口。

    payload 形如：
        {"handler": "specialized", "tool": "run_pytest", "params": {...}}
    或：
        {"handler": "specialized", "tool": "list_tools"}
    """
    tool_name = str(payload.get("tool") or "").strip()
    if not tool_name:
        # 未指定 tool → 返回该员工可用的工具清单
        available = get_employee_tools(employee_id)
        return _ok(
            f"员工 {employee_id} 可用 {len(available)} 个专属工具",
            employee_id=employee_id,
            available_tools=available,
            handler="specialized",
        )

    allowed = get_employee_tools(employee_id)
    if tool_name not in allowed:
        return _err(
            f"工具 {tool_name!r} 不在员工 {employee_id} 的专属工具清单中。可用: {allowed}",
            employee_id=employee_id,
            available_tools=allowed,
        )

    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None or not callable(fn):
        return _err(f"工具 {tool_name!r} 未实现")

    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return _err("params 必须为对象")

    # 代码修改工具走 workspace_guard + write_approval gate（纵深防御）
    if tool_name in _code_write_tools():
        gate_verdict = await _check_write_gate(employee_id, tool_name, params, ctx)
        if not gate_verdict.get("ok", True):
            return _err(
                f"写操作被 gate 拦截: {gate_verdict.get('reason', '')}",
                blocked=True,
                gate_result=gate_verdict,
                pending_approval=bool(gate_verdict.get("pending_approval")),
                approval_request_ids=list(gate_verdict.get("approval_request_ids") or []),
            )

    try:
        result = await fn(params, ctx)
    except Exception as exc:  # noqa: BLE001  工具调度边界：任何异常都转为结构化结果
        return _err(f"工具 {tool_name!r} 执行异常: {exc!r}")

    if not isinstance(result, dict):
        return _ok(f"工具 {tool_name!r} 完成", raw=result)

    result.setdefault("tool", tool_name)
    result.setdefault("employee_id", employee_id)
    result.setdefault("handler", "specialized")
    return result
