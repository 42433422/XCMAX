"""Quality, contract and platform build commands with explicit runner inputs."""

from __future__ import annotations

import shutil

from .ports import Payload, QualityPorts
from .results import _command_result, _err, _ok


async def run_pytest(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """运行 pytest 测试套件。"""
    args = params.get("args") or ["tests/", "-q", "--tb=short"]
    if isinstance(args, str):
        args = args.split()
    env = {"XCAGI_SKIP_LEGACY_COMPAT_ROUTES": "1"}
    extra_env = params.get("env") or {}
    if isinstance(extra_env, dict):
        env.update(extra_env)
    r = await ports.run(
        [ports.python, "-m", "pytest", *[str(a) for a in args]],
        cwd=ports.root,
        timeout=int(params.get("timeout", 600)),
        env=env,
    )
    return _command_result("pytest", r, stdout_limit=8000, stderr_limit=4000)


async def run_ruff_check(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """运行 ruff lint 检查。"""
    targets = params.get("targets") or ["app/", "tests/"]
    if isinstance(targets, str):
        targets = targets.split()
    r = await ports.run(
        [ports.python, "-m", "ruff", "check", *[str(t) for t in targets]], cwd=ports.root
    )
    return _command_result("ruff check", r, stdout_limit=6000, stderr_limit=3000)


async def run_ruff_format(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """运行 ruff format 检查。"""
    targets = params.get("targets") or ["app/", "tests/"]
    if isinstance(targets, str):
        targets = targets.split()
    r = await ports.run(
        [ports.python, "-m", "ruff", "format", "--check", *[str(t) for t in targets]],
        cwd=ports.root,
    )
    return _command_result("ruff format", r, stdout_limit=4000, stderr_limit=2000)


async def run_mypy(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """运行 mypy 类型检查。"""
    targets = params.get("targets") or ["app/"]
    if isinstance(targets, str):
        targets = targets.split()
    r = await ports.run(
        [ports.python, "-m", "mypy", *[str(t) for t in targets]], cwd=ports.root, timeout=300
    )
    return _command_result("mypy", r, stdout_limit=8000, stderr_limit=4000)


async def check_coverage(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """检查覆盖率棘轮（只升不降）。"""
    r = await ports.script(ports.scripts / "dev" / "coverage_ratchet.py", "--check", cwd=ports.root)
    return _command_result("coverage ratchet", r, stdout_limit=4000, stderr_limit=2000)


async def count_type_debt(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """统计类型债务。"""
    r = await ports.script(ports.scripts / "dev" / "count_type_debt.py", cwd=ports.root)
    return _command_result("type debt", r, stdout_limit=4000, stderr_limit=2000)


async def count_raw_sql(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """统计 SQL 债务。"""
    r = await ports.script(ports.scripts / "dev" / "count_raw_sql.py", cwd=ports.root)
    return _command_result("raw sql", r, stdout_limit=4000, stderr_limit=2000)


async def run_arch_fitness(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """运行架构适配度检查。"""
    r = await ports.script(ports.root / "scripts" / "arch_fitness.py", cwd=ports.root)
    return _command_result("arch fitness", r, stdout_limit=6000, stderr_limit=3000)


async def verify_version_anchors(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """校验版本锚点。"""
    r = await ports.script(ports.scripts / "dev" / "verify_version_anchors.py", cwd=ports.root)
    return _command_result("version anchors", r, stdout_limit=4000, stderr_limit=2000)


async def verify_employee_contract(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """验证员工契约。"""
    r = await ports.script(ports.scripts / "dev" / "verify_employee_contract.py", cwd=ports.root)
    return _command_result("employee contract", r, stdout_limit=6000, stderr_limit=3000)


async def mutation_kill_report(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """变异测试杀死率报告。"""
    r = await ports.script(
        ports.scripts / "dev" / "mutation_kill_report.py", cwd=ports.root, timeout=600
    )
    return _command_result("mutation kill", r, stdout_limit=6000, stderr_limit=3000)


async def frontend_lint(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """前端 ESLint 检查。"""
    return await _frontend(ports, "lint", "eslint")


async def frontend_typecheck(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """前端 vue-tsc 类型检查。"""
    return await _frontend(ports, "type-check", "type-check")


async def frontend_test(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """前端 Vitest 单元测试。"""
    return await _frontend(ports, "test", "vitest")


async def android_gradle_build(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """Flutter Android debug 构建检查（外部工具名为兼容既有调用保留）。"""
    if not params.get("confirm"):
        return _err("android_gradle_build 需 confirm=true 确认", requires_confirm=True)
    flutter_dir = ports.root / "mobile-flutter-poc"
    if not (flutter_dir / "pubspec.yaml").is_file():
        return _err("mobile-flutter-poc/pubspec.yaml 不存在")
    flutter = shutil.which("flutter")
    if not flutter:
        return _ok("flutter 未安装（跳过）", skipped=True)
    r = await ports.run([flutter, "build", "apk", "--debug"], cwd=flutter_dir, timeout=900)
    return _command_result("flutter build apk", r, stdout_limit=6000, stderr_limit=3000)


async def sandbox_python(ports: QualityPorts, params: Payload, ctx: Payload) -> Payload:
    """执行受确认门禁的项目 Python 检查（30 秒超时）；不提供操作系统沙箱。"""
    code = str(params.get("code") or "").strip()
    if not code:
        return _err("缺少 code 参数")
    if len(code) > 20000:
        return _err("代码过长（>20KB）")
    for forbidden in ("import os", "import subprocess", "import shutil", "open(", "__import__"):
        if forbidden in code and (not params.get("confirm")):
            return _err(f"检测到受限操作 {forbidden!r}，需 confirm=true", requires_confirm=True)
    r = await ports.run(
        [ports.python, "-c", code], cwd=ports.root, timeout=30, env={"XCAGI_SANDBOX": "1"}
    )
    return _command_result("sandbox", r, stdout_limit=4000, stderr_limit=2000)


async def _frontend(ports: QualityPorts, command: str, label: str) -> Payload:
    directory = ports.root / "frontend"
    if not (directory / "package.json").is_file():
        return _err("frontend/package.json 不存在")
    npm = shutil.which("npm")
    if not npm:
        return _ok("npm 未安装（跳过）", skipped=True)
    result = await ports.run([npm, "run", command], cwd=directory, timeout=300)
    return _command_result(label, result, stdout_limit=6000, stderr_limit=3000)
