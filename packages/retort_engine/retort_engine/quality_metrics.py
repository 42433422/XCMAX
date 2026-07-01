from __future__ import annotations

from pathlib import Path
from typing import Any

from retort_engine.quality_policy import TEST_TO_SOURCE_HEALTHY_RATIO, test_source_ratio_status


GENERATED_ABSORPTION_NAMES = {
    "retort_absorption_log.md",
    "retort_external_review_report.json",
    "absorbed_external_patterns.py",
    "retort_absorbed_patterns.py",
    "absorbed_capabilities.py",
    "test_absorbed_capabilities.py",
}
BEHAVIOR_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".go"}


def test_code_health(root: Path, *, latest: dict[str, Any] | None = None) -> dict[str, Any]:
    files = project_files(root, {".git", ".retort", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".ruff_cache"})
    source_lines = 0
    test_lines = 0
    source_files = 0
    test_files = 0
    for path in files:
        rel = project_relative(root, path)
        if is_generated_absorption_file(rel):
            continue
        if is_behavior_test_file(rel):
            test_files += 1
            test_lines += code_line_count(path)
        elif is_project_behavior_source_file(rel):
            source_files += 1
            source_lines += code_line_count(path)
    ratio = round(test_lines / source_lines, 3) if source_lines else 0.0
    latest_health = latest_absorption_change_health(root, latest or {})
    return {
        "source_file_count": source_files,
        "test_file_count": test_files,
        "source_line_count": source_lines,
        "test_line_count": test_lines,
        "test_to_source_ratio": ratio,
        "test_to_source_ratio_target": TEST_TO_SOURCE_HEALTHY_RATIO,
        "test_to_source_ratio_status": test_source_ratio_status(ratio),
        "latest_changed_file_count": latest_health["latest_changed_file_count"],
        "latest_changed_source_file_count": latest_health["latest_changed_source_file_count"],
        "latest_changed_test_file_count": latest_health["latest_changed_test_file_count"],
        "latest_changed_other_file_count": latest_health["latest_changed_other_file_count"],
        "latest_changed_source_line_count": latest_health["latest_changed_source_line_count"],
        "latest_changed_test_line_count": latest_health["latest_changed_test_line_count"],
        "latest_test_to_source_ratio": latest_health["latest_test_to_source_ratio"],
        "latest_test_to_source_ratio_target": TEST_TO_SOURCE_HEALTHY_RATIO,
        "latest_test_to_source_ratio_status": test_source_ratio_status(latest_health["latest_test_to_source_ratio"]),
        "latest_code_graph_proof_path": latest_health["latest_code_graph_proof_path"],
    }


def latest_absorption_change_health(root: Path, latest: dict[str, Any]) -> dict[str, Any]:
    changed_files = [str(item) for item in latest.get("changed_files") or []]
    source_files: list[str] = []
    test_files: list[str] = []
    other_files: list[str] = []
    source_lines = 0
    test_lines = 0
    for item in changed_files:
        path = Path(item)
        rel = project_relative(root, path)
        if is_generated_absorption_file(rel):
            other_files.append(rel)
            continue
        if not path.is_file():
            other_files.append(rel)
            continue
        if is_behavior_test_file(rel):
            test_files.append(rel)
            test_lines += code_line_count(path)
        elif is_project_behavior_source_file(rel):
            source_files.append(rel)
            source_lines += code_line_count(path)
        else:
            other_files.append(rel)
    ratio = round(test_lines / source_lines, 3) if source_lines else 0.0
    return {
        "latest_changed_file_count": len(changed_files),
        "latest_changed_source_file_count": len(source_files),
        "latest_changed_test_file_count": len(test_files),
        "latest_changed_other_file_count": len(other_files),
        "latest_changed_source_line_count": source_lines,
        "latest_changed_test_line_count": test_lines,
        "latest_test_to_source_ratio": ratio,
        "latest_code_graph_proof_path": str(latest.get("code_graph_proof_path") or ""),
    }


def project_files(root: Path, skip_parts: set[str]) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in skip_parts for part in rel_parts):
            continue
        files.append(path)
    return files


def project_relative(root: Path, path: Path) -> str:
    try:
        return str(path.expanduser().resolve().relative_to(root.expanduser().resolve()))
    except (OSError, ValueError):
        return str(path)


def is_generated_absorption_file(rel: str) -> bool:
    path = Path(rel)
    if path.name in GENERATED_ABSORPTION_NAMES:
        return True
    if rel.startswith(".retort/"):
        return True
    path_text = path.as_posix()
    return path_text.startswith("docs/retort_") and path.suffix == ".json"


def is_behavior_test_file(rel: str) -> bool:
    path = Path(rel)
    return path.suffix.lower() in BEHAVIOR_SUFFIXES and ("tests" in path.parts or path.name.startswith("test_"))


def is_project_behavior_source_file(rel: str) -> bool:
    path = Path(rel)
    return path.suffix.lower() in BEHAVIOR_SUFFIXES and not is_generated_absorption_file(rel) and not is_behavior_test_file(rel)


def code_line_count(path: Path) -> int:
    lines = 0
    for line in read_text(path).splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
            lines += 1
    return lines


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
