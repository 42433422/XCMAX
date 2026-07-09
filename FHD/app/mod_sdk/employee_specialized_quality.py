"""Quality tools."""

from __future__ import annotations

from typing import Any

from app.mod_sdk.employee_specialized_runtime import (
    _FHD_ROOT,
    _PYTHON,
    _SCRIPTS,
    _facade_attr,
    _ok,
    _run_cmd,
    _run_python_script,
)


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
        [_facade_attr("_PYTHON", _PYTHON), "-m", "pytest", *[str(a) for a in args]],
        cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT),
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
    r = await _run_cmd([_facade_attr("_PYTHON", _PYTHON), "-m", "ruff", "check", *[str(t) for t in targets]], cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT))
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
        [_facade_attr("_PYTHON", _PYTHON), "-m", "ruff", "format", "--check", *[str(t) for t in targets]], cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT)
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
        [_facade_attr("_PYTHON", _PYTHON), "-m", "mypy", *[str(t) for t in targets]], cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT), timeout=300
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
    r = await _run_python_script(_facade_attr("_SCRIPTS", _SCRIPTS) / "dev" / "coverage_ratchet.py", "--check", cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT))
    return _ok(
        f"coverage ratchet exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_count_type_debt(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """统计类型债务。"""
    r = await _run_python_script(_facade_attr("_SCRIPTS", _SCRIPTS) / "dev" / "count_type_debt.py", cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT))
    return _ok(
        f"type debt exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_count_raw_sql(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """统计 SQL 债务。"""
    r = await _run_python_script(_facade_attr("_SCRIPTS", _SCRIPTS) / "dev" / "count_raw_sql.py", cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT))
    return _ok(
        f"raw sql exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-4000:],
        stderr=r["stderr"][-2000:],
        passed=r["ok"],
    )


async def tool_run_arch_fitness(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """运行架构适配度检查。"""
    r = await _run_python_script(_facade_attr("_FHD_ROOT", _FHD_ROOT) / "scripts" / "arch_fitness.py", cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT))
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
    r = await _run_python_script(_facade_attr("_SCRIPTS", _SCRIPTS) / "dev" / "verify_version_anchors.py", cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT))
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
    r = await _run_python_script(_facade_attr("_SCRIPTS", _SCRIPTS) / "dev" / "verify_employee_contract.py", cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT))
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
        _facade_attr("_SCRIPTS", _SCRIPTS) / "dev" / "mutation_kill_report.py", cwd=_facade_attr("_FHD_ROOT", _FHD_ROOT), timeout=600
    )
    return _ok(
        f"mutation kill exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"][-6000:],
        stderr=r["stderr"][-3000:],
        passed=r["ok"],
    )

