"""Repository inspection and explicitly confirmed release operations."""

from __future__ import annotations

import shutil

from .employee_tool_ports import Payload, ReleasePorts
from .results import _command_result, _err, _ok


async def git_status(ports: ReleasePorts, params: Payload, ctx: Payload) -> Payload:
    """git status --porcelain。"""
    r = await ports.run(["git", "status", "--porcelain"], cwd=ports.root)
    lines = [l for l in r["stdout"].splitlines() if l.strip()]
    return _ok(f"{len(lines)} 个变更", files=lines, clean=len(lines) == 0, raw=r["stdout"])


async def git_log(ports: ReleasePorts, params: Payload, ctx: Payload) -> Payload:
    """git log --oneline。"""
    n = str(params.get("n", 20))
    r = await ports.run(["git", "log", "--oneline", f"-{n}"], cwd=ports.root)
    commits = [l for l in r["stdout"].splitlines() if l.strip()]
    return _ok(f"最近 {len(commits)} 条提交", commits=commits)


async def git_diff(ports: ReleasePorts, params: Payload, ctx: Payload) -> Payload:
    """git diff（unstaged 或指定 ref）。"""
    ref = params.get("ref") or ""
    args = ["git", "diff", *([ref] if ref else [])]
    if params.get("stat"):
        args.append("--stat")
    r = await ports.run(args, cwd=ports.root)
    return _ok("git diff", diff=r["stdout"][-8000:], returncode=r["returncode"])


async def git_branch(ports: ReleasePorts, params: Payload, ctx: Payload) -> Payload:
    """当前分支名。"""
    r = await ports.run(["git", "branch", "--show-current"], cwd=ports.root)
    return _ok(f"branch={r['stdout'].strip()}", branch=r["stdout"].strip())


async def pack_release(ports: ReleasePorts, params: Payload, ctx: Payload) -> Payload:
    """打包发布 tarball（需 confirm）。"""
    if not params.get("confirm"):
        return _err("pack_release 需 confirm=true 确认", requires_confirm=True)
    script = ports.root / "scripts" / "deploy" / "fhd-pack-release.sh"
    r = await ports.run(["bash", str(script)], cwd=ports.root, timeout=600)
    return _command_result("pack", r, stdout_limit=6000, stderr_limit=3000)


async def list_deploy_scripts(ports: ReleasePorts, params: Payload, ctx: Payload) -> Payload:
    """列出部署脚本。"""
    deploy_dir = ports.root / "scripts" / "deploy"
    scripts = sorted(p.name for p in deploy_dir.glob("*.sh")) if deploy_dir.is_dir() else []
    return _ok(f"{len(scripts)} 个部署脚本", scripts=scripts)


async def trigger_gh_workflow(ports: ReleasePorts, params: Payload, ctx: Payload) -> Payload:
    """通过 gh CLI 触发 GitHub Actions workflow（需 confirm）。"""
    if not params.get("confirm"):
        return _err("trigger_gh_workflow 需 confirm=true 确认", requires_confirm=True)
    workflow = str(params.get("workflow") or "").strip()
    if not workflow:
        return _err("缺少 workflow 参数")
    ref = str(params.get("ref") or "main")
    r = await ports.run(["gh", "workflow", "run", workflow, "--ref", ref], cwd=ports.root)
    return _command_result("gh workflow run", r)


async def nginx_test(ports: ReleasePorts, params: Payload, ctx: Payload) -> Payload:
    """nginx -t 语法检查。"""
    nginx = shutil.which("nginx")
    if not nginx:
        return _ok("nginx 未安装（跳过）", skipped=True, syntax_valid=None)
    r = await ports.run([nginx, "-t"])
    return _ok(
        f"nginx -t exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"],
        stderr=r["stderr"],
        syntax_valid=r["ok"],
    )


async def disk_usage(ports: ReleasePorts, params: Payload, ctx: Payload) -> Payload:
    """磁盘使用情况。"""
    r = await ports.run(["df", "-h", str(ports.root)])
    return _ok("df -h", output=r["stdout"])
