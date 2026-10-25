"""Project reads and target-scoped writes; each patch owns its temporary artifact."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .employee_tool_ports import Payload, WorkspacePorts
from .results import _err, _ok


async def tail_logs(ports: WorkspacePorts, params: Payload, ctx: Payload) -> Payload:
    """读取最近 N 行日志。"""
    log_dir = ports.root / "logs"
    if not log_dir.is_dir():
        return _ok("logs 目录不存在", lines=[])
    n = int(params.get("lines", 100))
    log_file = params.get("file") or "app.log"
    target = _within(log_dir, str(log_file))
    if target is None:
        return _err("路径越界（仅限日志目录）")
    if not target.is_file():
        files = sorted(p.name for p in log_dir.glob("*.log"))
        return _ok(f"{log_file} 不存在", available_files=files)
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError as exc:
        return _err(f"读取日志失败: {exc}")
    return _ok(f"{len(lines)} 行", lines=lines)


async def list_docs(ports: WorkspacePorts, params: Payload, ctx: Payload) -> Payload:
    """列出项目文档。"""
    doc_dirs = [ports.root / "docs", ports.root.parent / "docs"]
    docs: list[str] = []
    for d in doc_dirs:
        if d.is_dir():
            docs.extend(str(p.relative_to(ports.root.parent)) for p in d.rglob("*.md"))
    docs = sorted(set(docs))
    return _ok(f"{len(docs)} 个文档", docs=docs)


async def read_file(ports: WorkspacePorts, params: Payload, ctx: Payload) -> Payload:
    """读取文件内容（限项目内、限 50KB）。"""
    rel = str(params.get("path") or "").strip()
    if not rel:
        return _err("缺少 path 参数")
    target = (ports.root / rel).resolve()
    try:
        target.relative_to(ports.root)
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


async def list_scripts(ports: WorkspacePorts, params: Payload, ctx: Payload) -> Payload:
    """列出项目脚本。"""
    scripts_dir = ports.root / "scripts"
    if not scripts_dir.is_dir():
        return _ok("scripts 目录不存在", scripts=[])
    category = str(params.get("category") or "").strip()
    search_dir = _within(scripts_dir, category)
    if search_dir is None:
        return _err("路径越界（仅限 scripts 目录）")
    if not search_dir.is_dir():
        return _err(f"目录不存在: scripts/{category}")
    pys = sorted(str(p.relative_to(ports.root.resolve())) for p in search_dir.rglob("*.py"))
    shs = sorted(str(p.relative_to(ports.root.resolve())) for p in search_dir.rglob("*.sh"))
    return _ok(f"{len(pys)} py + {len(shs)} sh", python=pys, shell=shs)


async def list_workbench_sessions(ports: WorkspacePorts, params: Payload, ctx: Payload) -> Payload:
    """列出 workbench 会话。"""
    ws_root = Path(ctx.get("workspace_root") or ports.root)
    sessions_dir = ws_root / "workbench" / "sessions"
    if not sessions_dir.is_dir():
        return _ok("workbench/sessions 不存在", sessions=[])
    sessions = sorted(p.name for p in sessions_dir.iterdir() if p.is_dir())
    return _ok(f"{len(sessions)} 个会话", sessions=sessions)


async def write_file(ports: WorkspacePorts, params: Payload, ctx: Payload) -> Payload:
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
    except OSError as exc:
        return _err(f"写入失败: {exc!r}")
    return _ok(
        f"已写入 {rel_path}（{len(content)} 字符）",
        path=rel_path,
        bytes_written=len(content.encode()),
    )


async def patch_file(ports: WorkspacePorts, params: Payload, ctx: Payload) -> Payload:
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
    patch_tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".tmp-patch-",
            suffix=".diff",
            dir=root,
            delete=False,
        ) as stream:
            patch_tmp = Path(stream.name)
            stream.write(patch)
        check = await ports.run(
            ["git", "apply", "--check", "--numstat", "-z", str(patch_tmp)], cwd=root, timeout=15
        )
        if not check.get("ok"):
            return _err(f"patch 校验失败: {check.get('stderr', '')[:500]}")
        if not _patch_targets_requested_file(str(check.get("stdout") or ""), root, target):
            return _err("patch 只能修改 params.path 指定的单个文件")
        apply = await ports.run(["git", "apply", str(patch_tmp)], cwd=root, timeout=15)
        if not apply.get("ok"):
            return _err(f"patch 应用失败: {apply.get('stderr', '')[:500]}")
    finally:
        if patch_tmp is not None:
            try:
                patch_tmp.unlink(missing_ok=True)
            except OSError:
                pass
    return _ok(f"已应用 patch 到 {rel_path}", path=rel_path)


def _within(root: Path, name: str) -> Path | None:
    try:
        base = root.resolve()
        target = (base / name).resolve()
        target.relative_to(base)
        return target
    except (OSError, RuntimeError, ValueError):
        return None


def _patch_targets_requested_file(stat: str, root: Path, target: Path) -> bool:
    """Git's NUL-delimited dry-run names, including quoted/unicode paths, are authoritative."""
    records = [record for record in stat.split("\0") if record]
    if len(records) != 1:
        return False
    fields = records[0].split("\t", 2)
    if len(fields) != 3 or any(value != "-" and not value.isdigit() for value in fields[:2]):
        return False
    return _within(root, fields[2]) == target
