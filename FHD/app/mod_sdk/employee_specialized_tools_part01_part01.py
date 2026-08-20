# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.mod_sdk.employee_specialized_tools")


def _ok(summary: str, **extra: _facade().Any) -> dict[str, _facade().Any]:
    out: dict[str, _facade().Any] = {"ok": True, "summary": summary[:4000]}
    out.update(extra)
    return out


def _err(error: str, **extra: _facade().Any) -> dict[str, _facade().Any]:
    out: dict[str, _facade().Any] = {"ok": False, "error": error[:1000]}
    out.update(extra)
    return out


async def _run_cmd(
    args: list[str],
    *,
    cwd: str | _facade().Path | None = None,
    timeout: int = _facade()._DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> dict[str, _facade().Any]:
    """执行命令并返回结构化结果。"""
    proc: _facade().asyncio.subprocess.Process | None = None
    try:
        proc = await _facade().asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            stdout=_facade().asyncio.subprocess.PIPE,
            stderr=_facade().asyncio.subprocess.PIPE,
            env={**_facade().os.environ, **(env or {})},
        )
        communication = proc.communicate()
        try:
            stdout_b, stderr_b = await _facade().asyncio.wait_for(communication, timeout=timeout)
        finally:
            if _facade().inspect.iscoroutine(communication):
                communication.close()
        stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
        stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
        return {
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "ok": proc.returncode == 0,
        }
    except TimeoutError:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        return {"returncode": -1, "stdout": "", "stderr": f"timeout after {timeout}s", "ok": False}
    except FileNotFoundError as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc), "ok": False}
    except _facade().RECOVERABLE_ERRORS as exc:
        return {"returncode": -1, "stdout": "", "stderr": repr(exc), "ok": False}


async def _run_python_script(
    script: str | _facade().Path, *extra_args: str, **kw: _facade().Any
) -> dict[str, _facade().Any]:
    """用项目 venv python 跑一个脚本。"""
    return await _facade()._run_cmd([_facade()._PYTHON, str(script), *extra_args], **kw)


async def _api_call(
    method: str, path: str, *, api_base: str | None = None, **kw: _facade().Any
) -> dict[str, _facade().Any]:
    if _facade().httpx is None:
        return {"ok": False, "error": "httpx 未安装"}
    base = (api_base or _facade()._DEFAULT_API_BASE).rstrip("/")
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
    try:
        async with _facade().httpx.AsyncClient(timeout=kw.pop("timeout", 30)) as client:
            resp = await client.request(method, url, **kw)
            try:
                body = resp.json()
            except _facade().RECOVERABLE_ERRORS:
                body = resp.text
            return {"ok": resp.is_success, "status": resp.status_code, "body": body}
    except _facade().RECOVERABLE_ERRORS as exc:
        return {"ok": False, "error": repr(exc)}


async def tool_run_pytest(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """运行 pytest 测试套件。"""
    args = params.get("args") or ["tests/", "-q", "--tb=short"]
    if isinstance(args, str):
        args = args.split()
    env = {"XCAGI_SKIP_LEGACY_COMPAT_ROUTES": "1"}
    extra_env = params.get("env") or {}
    if isinstance(extra_env, dict):
        env.update(extra_env)
    r = await _facade()._run_cmd(
        [_facade()._PYTHON, "-m", "pytest", *[str(a) for a in args]],
        cwd=_facade()._FHD_ROOT,
        timeout=int(params.get("timeout", 600)),
        env=env,
    )
    return _facade()._ok(
        f"pytest exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-8000:],
        stderr=r["stderr"][-4000:],
        passed=r["ok"],
    )


async def tool_run_ruff_check(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """运行 ruff lint 检查。"""
    targets = params.get("targets") or ["app/", "tests/"]
    if isinstance(targets, str):
        targets = targets.split()
    r = await _facade()._run_cmd(
        [_facade()._PYTHON, "-m", "ruff", "check", *[str(t) for t in targets]],
        cwd=_facade()._FHD_ROOT,
    )
    return _facade()._ok(
        f"ruff check exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_run_ruff_format(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """运行 ruff format 检查。"""
    targets = params.get("targets") or ["app/", "tests/"]
    if isinstance(targets, str):
        targets = targets.split()
    r = await _facade()._run_cmd(
        [_facade()._PYTHON, "-m", "ruff", "format", "--check", *[str(t) for t in targets]],
        cwd=_facade()._FHD_ROOT,
    )
    return _facade()._ok(
        f"ruff format exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_run_mypy(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """运行 mypy 类型检查。"""
    targets = params.get("targets") or ["app/"]
    if isinstance(targets, str):
        targets = targets.split()
    r = await _facade()._run_cmd(
        [_facade()._PYTHON, "-m", "mypy", *[str(t) for t in targets]],
        cwd=_facade()._FHD_ROOT,
        timeout=300,
    )
    return _facade()._ok(
        f"mypy exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-8000:],
        stderr=r["stderr"][-4000:],
        passed=r["ok"],
    )


async def tool_check_coverage(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """检查覆盖率棘轮（只升不降）。"""
    r = await _facade()._run_python_script(
        _facade()._SCRIPTS / "dev" / "coverage_ratchet.py", "--check", cwd=_facade()._FHD_ROOT
    )
    return _facade()._ok(
        f"coverage ratchet exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_count_type_debt(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """统计类型债务。"""
    r = await _facade()._run_python_script(
        _facade()._SCRIPTS / "dev" / "count_type_debt.py", cwd=_facade()._FHD_ROOT
    )
    return _facade()._ok(
        f"type debt exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_count_raw_sql(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """统计 SQL 债务。"""
    r = await _facade()._run_python_script(
        _facade()._SCRIPTS / "dev" / "count_raw_sql.py", cwd=_facade()._FHD_ROOT
    )
    return _facade()._ok(
        f"raw sql exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_run_arch_fitness(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """运行架构适配度检查。"""
    r = await _facade()._run_python_script(
        _facade()._FHD_ROOT / "scripts" / "arch_fitness.py", cwd=_facade()._FHD_ROOT
    )
    return _facade()._ok(
        f"arch fitness exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_verify_version_anchors(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """校验版本锚点。"""
    r = await _facade()._run_python_script(
        _facade()._SCRIPTS / "dev" / "verify_version_anchors.py", cwd=_facade()._FHD_ROOT
    )
    return _facade()._ok(
        f"version anchors exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_verify_employee_contract(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """验证员工契约。"""
    r = await _facade()._run_python_script(
        _facade()._SCRIPTS / "dev" / "verify_employee_contract.py", cwd=_facade()._FHD_ROOT
    )
    return _facade()._ok(
        f"employee contract exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_mutation_kill_report(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """变异测试杀死率报告。"""
    r = await _facade()._run_python_script(
        _facade()._SCRIPTS / "dev" / "mutation_kill_report.py", cwd=_facade()._FHD_ROOT, timeout=600
    )
    return _facade()._ok(
        f"mutation kill exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_git_status(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """git status --porcelain。"""
    r = await _facade()._run_cmd(["git", "status", "--porcelain"], cwd=_facade()._FHD_ROOT)
    lines = [l for l in r["stdout"].splitlines() if l.strip()]
    return _facade()._ok(
        f"{len(lines)} 个变更", files=lines, clean=len(lines) == 0, raw=r["stdout"]
    )


async def tool_git_log(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """git log --oneline。"""
    n = str(params.get("n", 20))
    r = await _facade()._run_cmd(["git", "log", "--oneline", f"-{n}"], cwd=_facade()._FHD_ROOT)
    commits = [l for l in r["stdout"].splitlines() if l.strip()]
    return _facade()._ok(f"最近 {len(commits)} 条提交", commits=commits)


async def tool_git_diff(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """git diff（unstaged 或指定 ref）。"""
    ref = params.get("ref") or ""
    args = ["git", "diff", *([ref] if ref else [])]
    if params.get("stat"):
        args.append("--stat")
    r = await _facade()._run_cmd(args, cwd=_facade()._FHD_ROOT)
    return _facade()._ok("git diff", diff=r["stdout"][-8000:], returncode=r["returncode"])


async def tool_git_branch(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """当前分支名。"""
    r = await _facade()._run_cmd(["git", "branch", "--show-current"], cwd=_facade()._FHD_ROOT)
    return _facade()._ok(f"branch={r['stdout'].strip()}", branch=r["stdout"].strip())


async def tool_pack_release(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """打包发布 tarball（需 confirm）。"""
    if not params.get("confirm"):
        return _facade()._err("pack_release 需 confirm=true 确认", requires_confirm=True)
    script = _facade()._FHD_ROOT / "scripts" / "deploy" / "fhd-pack-release.sh"
    r = await _facade()._run_cmd(["bash", str(script)], cwd=_facade()._FHD_ROOT, timeout=600)
    return _facade()._ok(
        f"pack exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )


async def tool_list_deploy_scripts(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """列出部署脚本。"""
    deploy_dir = _facade()._FHD_ROOT / "scripts" / "deploy"
    scripts = sorted(p.name for p in deploy_dir.glob("*.sh")) if deploy_dir.is_dir() else []
    return _facade()._ok(f"{len(scripts)} 个部署脚本", scripts=scripts)
