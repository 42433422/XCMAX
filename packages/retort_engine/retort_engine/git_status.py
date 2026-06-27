from __future__ import annotations

import subprocess
from pathlib import Path


GENERATED_ABSORPTION_NAMES = {
    "retort_absorption_log.md",
    "retort_external_review_report.json",
    "absorbed_external_patterns.py",
    "retort_absorbed_patterns.py",
    "absorbed_capabilities.py",
    "test_absorbed_capabilities.py",
}
GIT_STATUS_RUNTIME_PARTS = {".retort", "__pycache__", ".pytest_cache", ".ruff_cache"}


def blocking_git_status(root: Path, project: Path) -> str:
    rel = _project_status_path(root, project)
    status = _git(root, "status", "--short", "--", rel)
    prefixes = _runtime_status_prefixes(root, project)
    blocking: list[str] = []
    for line in status.splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip().strip('"')
        if _is_exempt_git_status_path(path, prefixes, root=root):
            continue
        blocking.append(line)
    return "\n".join(blocking)


def _project_status_path(root: Path, project: Path) -> str:
    try:
        rel = project.resolve().relative_to(root.resolve())
    except ValueError:
        return "."
    return "." if str(rel) == "." else str(rel)


def _runtime_status_prefixes(root: Path, project: Path) -> tuple[str, ...]:
    try:
        rel = project.resolve().relative_to(root.resolve())
    except ValueError:
        return (".retort/",)
    rel_text = "" if str(rel) == "." else str(rel).rstrip("/") + "/"
    return (f"{rel_text}.retort/",)


def _is_exempt_git_status_path(path: str, prefixes: tuple[str, ...], *, root: Path | None = None) -> bool:
    normalized = path.replace("\\", "/")
    if any(normalized == prefix.removesuffix("/") or normalized.startswith(prefix) for prefix in prefixes):
        return True
    if root is not None and _directory_contains_only_exempt_status_files(root / normalized, root, prefixes):
        return True
    project_prefix = _project_prefix_from_runtime_prefixes(prefixes)
    if project_prefix and not normalized.startswith(project_prefix):
        return False
    project_rel = normalized[len(project_prefix) :] if project_prefix else normalized
    rel_path = Path(project_rel)
    if any(part in GIT_STATUS_RUNTIME_PARTS for part in rel_path.parts):
        return True
    if rel_path.name in GENERATED_ABSORPTION_NAMES:
        return True
    return (
        len(rel_path.parts) >= 2
        and rel_path.parts[0] == "docs"
        and rel_path.name.startswith("retort_")
        and rel_path.suffix == ".json"
    )


def _directory_contains_only_exempt_status_files(path: Path, root: Path, prefixes: tuple[str, ...]) -> bool:
    if not path.is_dir():
        return False
    files = [item for item in path.rglob("*") if item.is_file()]
    if not files:
        return False
    for item in files:
        try:
            rel = item.relative_to(root).as_posix()
        except ValueError:
            return False
        if not _is_exempt_git_status_path(rel, prefixes):
            return False
    return True


def _project_prefix_from_runtime_prefixes(prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if prefix.endswith(".retort/"):
            return prefix[: -len(".retort/")]
    return ""


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout
