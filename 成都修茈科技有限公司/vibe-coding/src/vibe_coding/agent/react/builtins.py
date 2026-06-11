"""Built-in tools the ReAct agent can use out of the box.

Categories:

- **Filesystem** (``read_file`` / ``write_file`` / ``list_dir`` /
  ``stat_path`` / ``apply_edit``).
- **Shell** (``run_command``) — executes via the project's
  :class:`SandboxDriver` so timeouts / memory caps / network isolation
  apply.
- **Search** (``grep`` / ``find_files``) — ``ripgrep``-flavoured but
  pure-Python so it works everywhere.
- **Git** (``git_status`` / ``git_diff`` / ``git_log``) — read-only.
- **Project** (``index_project`` / ``find_symbol`` /
  ``apply_project_patch``) — wraps the existing :class:`ProjectVibeCoder`
  so the agent can edit + commit hunks.
- **Web** (``web_search`` / ``http_fetch``) — opt-in; off by default
  because they require network access.

All tools enforce a project-rooted sandbox: paths are normalised via
:func:`vibe_coding.agent.security.paths.resolve_safe_path` so the LLM
can't ``../../etc/passwd`` its way out. Sets of allowed roots can be
configured at registration time.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..sandbox import SandboxDriver, SandboxJob, SandboxPolicy, SubprocessSandboxDriver
from ..security.paths import PathSafetyError, resolve_within_root
from .tools import Tool, ToolError, ToolRegistry, ToolResult, render_observation, tool


# ----------------------------------------------------------------- helpers


def _resolve(root: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` against ``root`` while honouring the path guard.

    Treats ``""`` / ``"."`` / ``"./"`` as the project root (the path
    guard rejects them, so we short-circuit before delegating).
    """
    safe_root = root.resolve()
    cleaned = (rel_path or "").strip().replace("\\", "/").lstrip("./")
    if not cleaned or rel_path.strip() in {".", "./"}:
        return safe_root
    try:
        return resolve_within_root(safe_root, rel_path, allow_existing_symlink=True)
    except PathSafetyError as exc:
        raise ToolError(f"unsafe path {rel_path!r}: {exc.reason}") from exc


def _format_diff(old: str, new: str, path: str) -> str:
    """Tiny unified-diff for observation rendering. No external deps."""
    import difflib

    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    return "".join(diff)[:6_000]


# ----------------------------------------------------------------- filesystem


def make_filesystem_tools(root: Path | str) -> list[Tool]:
    """Build the canonical filesystem tool set rooted at ``root``."""
    safe_root = Path(root).resolve()

    @tool(
        "read_file",
        description="Read a project-relative text file (≤ 256 KiB) and return its contents.",
    )
    def read_file(path: str, *, max_bytes: int = 256 * 1024) -> str:
        target = _resolve(safe_root, path)
        if not target.is_file():
            raise ToolError(f"{path!r} is not a file")
        if target.stat().st_size > max_bytes:
            raise ToolError(f"{path!r} too large ({target.stat().st_size} bytes)")
        return target.read_text(encoding="utf-8", errors="replace")

    @tool(
        "write_file",
        description="Overwrite (or create) a project-relative text file with `contents`.",
    )
    def write_file(path: str, contents: str) -> ToolResult:
        target = _resolve(safe_root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.is_file()
        old = target.read_text(encoding="utf-8", errors="replace") if existed else ""
        target.write_text(contents, encoding="utf-8")
        diff = _format_diff(old, contents, path) if existed else f"+ created {path}\n"
        return ToolResult(
            success=True,
            observation=f"wrote {len(contents)} bytes to {path}\n{diff}",
            output={"path": path, "bytes": len(contents), "existed": existed},
        )

    @tool(
        "list_dir",
        description="List entries in a project-relative directory (≤ 200 entries).",
    )
    def list_dir(path: str = ".", *, max_entries: int = 200) -> dict[str, Any]:
        target = _resolve(safe_root, path)
        if not target.is_dir():
            raise ToolError(f"{path!r} is not a directory")
        entries: list[dict[str, Any]] = []
        for child in sorted(target.iterdir()):
            try:
                stat = child.stat()
            except OSError:
                continue
            entries.append(
                {
                    "name": child.name,
                    "kind": "dir" if child.is_dir() else "file",
                    "size": int(stat.st_size),
                }
            )
            if len(entries) >= max_entries:
                break
        return {"path": path, "entries": entries}

    @tool(
        "stat_path",
        description="Return basic metadata (kind/size/exists) for a project-relative path.",
    )
    def stat_path(path: str) -> dict[str, Any]:
        target = _resolve(safe_root, path)
        if not target.exists():
            return {"path": path, "exists": False}
        stat = target.stat()
        return {
            "path": path,
            "exists": True,
            "kind": "dir" if target.is_dir() else "file",
            "size": int(stat.st_size),
            "mtime": stat.st_mtime,
        }

    @tool(
        "apply_edit",
        description=(
            "Replace `old_text` with `new_text` in `path`. The match must be unique; "
            "use a longer `old_text` (with leading/trailing context) to disambiguate."
        ),
    )
    def apply_edit(path: str, old_text: str, new_text: str) -> ToolResult:
        target = _resolve(safe_root, path)
        if not target.is_file():
            raise ToolError(f"{path!r} is not a file")
        original = target.read_text(encoding="utf-8")
        count = original.count(old_text)
        if count == 0:
            raise ToolError(
                f"old_text not found in {path}; first 200 chars of file:\n{original[:200]!r}"
            )
        if count > 1:
            raise ToolError(
                f"old_text appears {count} times in {path}; expand it for uniqueness"
            )
        patched = original.replace(old_text, new_text, 1)
        target.write_text(patched, encoding="utf-8")
        return ToolResult(
            success=True,
            observation=(
                f"applied edit to {path} (-{old_text.count(chr(10)) + 1} +{new_text.count(chr(10)) + 1} lines)\n"
                + _format_diff(original, patched, path)
            ),
            output={"path": path, "lines_added": new_text.count("\n") - old_text.count("\n")},
        )

    return [read_file, write_file, list_dir, stat_path, apply_edit]


# --------------------------------------------------------------------- shell


def make_shell_tool(
    root: Path | str,
    *,
    sandbox: SandboxDriver | None = None,
    policy: SandboxPolicy | None = None,
    allowlist: tuple[str, ...] | None = None,
) -> Tool:
    """Run a shell command inside the sandbox driver.

    ``allowlist`` (when set) restricts the first token of ``command``;
    great for keeping the agent away from ``rm -rf`` and friends.
    """
    safe_root = Path(root).resolve()
    drv = sandbox or SubprocessSandboxDriver()
    pol = policy or SandboxPolicy(timeout_s=60, max_output_size=20_000)

    @tool(
        "run_command",
        description=(
            "Run a shell command (list of strings) inside the project root via the sandbox. "
            "Returns stdout/stderr/exit_code. The sandbox enforces timeout & resource caps."
        ),
        arguments=[
            {
                "name": "command",
                "type": "array",
                "description": 'argv list, e.g. ["pytest", "-q"]',
                "required": True,
            },
            {
                "name": "stdin",
                "type": "string",
                "description": "optional stdin payload",
                "required": False,
            },
        ],
    )
    def run_command(command: list[str], *, stdin: str = "") -> dict[str, Any]:
        if not command or not isinstance(command, list):
            raise ToolError("command must be a non-empty list of strings")
        head = str(command[0])
        if allowlist is not None and head not in allowlist:
            raise ToolError(f"command {head!r} not in allowlist {list(allowlist)}")
        res = drv.execute(
            SandboxJob(
                kind="command",
                workspace_dir=str(safe_root),
                command=[str(c) for c in command],
                stdin=stdin or "",
            ),
            policy=pol,
        )
        return {
            "command": list(command),
            "success": bool(res.success),
            "exit_code": int(res.exit_code),
            "stdout": res.stdout,
            "stderr": res.stderr,
            "duration_ms": res.duration_ms,
        }

    return run_command


# ----------------------------------------------------------------- search


def make_search_tools(root: Path | str) -> list[Tool]:
    """Plain-Python grep + glob that work cross-platform without ``rg``."""
    safe_root = Path(root).resolve()

    @tool(
        "grep",
        description=(
            "Recursively search project files for `pattern` (regex). "
            "Returns a capped list of `{file, line, snippet}` matches."
        ),
        arguments=[
            {"name": "pattern", "type": "string", "required": True, "description": "regex"},
            {
                "name": "path",
                "type": "string",
                "required": False,
                "description": "subdir to search; default the project root",
            },
            {
                "name": "include",
                "type": "string",
                "required": False,
                "description": "glob filter, e.g. \"*.py\"",
            },
            {
                "name": "max_results",
                "type": "integer",
                "required": False,
                "description": "default 100",
            },
        ],
    )
    def grep(
        pattern: str,
        *,
        path: str = ".",
        include: str = "",
        max_results: int = 100,
    ) -> dict[str, Any]:
        target = _resolve(safe_root, path)
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise ToolError(f"invalid regex: {exc}") from exc
        matches: list[dict[str, Any]] = []
        if not target.exists():
            raise ToolError(f"{path!r} does not exist")
        files = [target] if target.is_file() else _iter_files(target, max_files=20_000)
        for fp in files:
            if include and not fnmatch.fnmatch(fp.name, include):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for ln, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    rel = fp.relative_to(safe_root).as_posix()
                    matches.append(
                        {"file": rel, "line": ln, "snippet": line.strip()[:240]}
                    )
                    if len(matches) >= max_results:
                        return {"pattern": pattern, "matches": matches, "truncated": True}
        return {"pattern": pattern, "matches": matches, "truncated": False}

    @tool(
        "find_files",
        description="Glob the project for files matching `pattern` (e.g. `**/*.py`).",
    )
    def find_files(pattern: str, *, max_results: int = 200) -> dict[str, Any]:
        out: list[str] = []
        for fp in safe_root.glob(pattern):
            if fp.is_file():
                out.append(fp.relative_to(safe_root).as_posix())
                if len(out) >= max_results:
                    break
        return {"pattern": pattern, "files": out}

    return [grep, find_files]


def _iter_files(root: Path, *, max_files: int = 20_000):
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "dist", "build", ".cache"}
    count = 0
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for f in files:
            yield Path(cur) / f
            count += 1
            if count >= max_files:
                return


# ----------------------------------------------------------------- git


def make_git_tools(root: Path | str) -> list[Tool]:
    """Read-only git inspection helpers."""
    safe_root = Path(root).resolve()

    def _run_git(args: list[str], timeout_s: float = 10.0) -> str:
        if shutil.which("git") is None:
            raise ToolError("git not on PATH")
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(safe_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"git timed out after {timeout_s}s") from exc
        if proc.returncode != 0:
            raise ToolError(f"git failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout

    @tool("git_status", description="Run `git status --porcelain=v1` against the project root.")
    def git_status() -> str:
        return _run_git(["status", "--porcelain=v1"])

    @tool("git_diff", description="Run `git diff` (optionally for one path).")
    def git_diff(path: str = "") -> str:
        args = ["diff", "--no-color"]
        if path:
            args.append(path)
        return _run_git(args)

    @tool(
        "git_log",
        description="Show the last `limit` commits as `sha\\tsubject`.",
    )
    def git_log(limit: int = 10) -> str:
        return _run_git(["log", f"-n{int(limit)}", "--pretty=format:%h\t%s"])

    return [git_status, git_diff, git_log]


# ----------------------------------------------------------------- project


def make_project_tools(project_coder: Any) -> list[Tool]:
    """Wrap the user's :class:`ProjectVibeCoder` so the agent can index / patch."""

    @tool(
        "index_project",
        description="Build (or refresh) the RepoIndex for the active project.",
    )
    def index_project_(refresh: bool = False) -> dict[str, Any]:
        index = project_coder.index_project(refresh=bool(refresh))
        return index.summary()

    @tool(
        "find_symbol",
        description="Look up symbols by name across the indexed project.",
    )
    def find_symbol(name: str) -> list[dict[str, Any]]:
        index = project_coder.index_project()
        results = index.find_symbol(name)
        return [s.to_dict() for s in results[:50]]

    @tool(
        "apply_project_patch",
        description=(
            "Generate + apply a multi-file patch for the given brief via the configured ProjectVibeCoder. "
            "Returns the apply-result dict."
        ),
    )
    def apply_project_patch(brief: str, *, dry_run: bool = False) -> dict[str, Any]:
        if not brief or not brief.strip():
            raise ToolError("brief required")
        patch = project_coder.edit_project(brief)
        result = project_coder.apply_patch(patch, dry_run=bool(dry_run))
        return {
            "patch_id": patch.patch_id,
            "summary": patch.summary,
            "applied": bool(result.applied),
            "error": getattr(result, "error", "") or "",
            "files": [f.path for f in getattr(result, "files", [])],
        }

    return [index_project_, find_symbol, apply_project_patch]


# ----------------------------------------------------------------- web (opt-in)


def make_web_tools(*, allow_network: bool = False) -> list[Tool]:
    """Tools that require network access. Off by default."""

    @tool(
        "http_fetch",
        description=(
            "Fetch the body of an HTTP/HTTPS URL (≤ 256 KiB). Disabled unless "
            "the registry was built with allow_network=True."
        ),
    )
    def http_fetch(url: str, *, max_bytes: int = 256 * 1024) -> dict[str, Any]:
        if not allow_network:
            raise ToolError("network access disabled; rebuild registry with allow_network=True")
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ToolError("only http(s) URLs are allowed")
        import urllib.error
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "vibe-coding/agent"})
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                data = resp.read(max_bytes + 1)
                truncated = len(data) > max_bytes
                if truncated:
                    data = data[:max_bytes]
                return {
                    "url": url,
                    "status": int(getattr(resp, "status", 200)),
                    "body": data.decode("utf-8", errors="replace"),
                    "truncated": truncated,
                }
        except urllib.error.HTTPError as exc:
            return {"url": url, "status": int(exc.code), "body": "", "truncated": False, "error": str(exc)}
        except urllib.error.URLError as exc:
            raise ToolError(f"network error: {exc.reason}") from exc

    return [http_fetch]


# ----------------------------------------------------------------- bundle


def builtin_tools(
    *,
    root: Path | str,
    sandbox: SandboxDriver | None = None,
    policy: SandboxPolicy | None = None,
    allow_network: bool = False,
    project_coder: Any = None,
    shell_allowlist: tuple[str, ...] | None = None,
) -> ToolRegistry:
    """Compose the full default tool set rooted at ``root``.

    Pass ``project_coder`` (a :class:`ProjectVibeCoder`) to enable the
    higher-level project tools (``index_project`` / ``find_symbol`` /
    ``apply_project_patch``). Without it the agent still gets file I/O,
    grep, git, and shell.
    """
    reg = ToolRegistry()
    for t in make_filesystem_tools(root):
        reg.register(t)
    reg.register(make_shell_tool(root, sandbox=sandbox, policy=policy, allowlist=shell_allowlist))
    for t in make_search_tools(root):
        reg.register(t)
    for t in make_git_tools(root):
        reg.register(t)
    if project_coder is not None:
        for t in make_project_tools(project_coder):
            reg.register(t)
    if allow_network:
        for t in make_web_tools(allow_network=True):
            reg.register(t)
    return reg


def register_project_tools(reg: ToolRegistry, project_coder: Any) -> None:
    """Mutate ``reg`` to add the project-aware tools after construction."""
    for t in make_project_tools(project_coder):
        reg.register(t)


__all__ = [
    "builtin_tools",
    "make_filesystem_tools",
    "make_git_tools",
    "make_project_tools",
    "make_search_tools",
    "make_shell_tool",
    "make_web_tools",
    "register_project_tools",
]


# Defensive: silence unused-import warning if security helpers aren't reached.
_ = render_observation
