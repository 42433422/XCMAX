#!/usr/bin/env python3
"""Audit Yuangon source contracts, dependency DAG, and repository ownership coverage."""

from __future__ import annotations

import argparse
import fnmatch
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

IGNORED_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "_generated_employee",
    "__pycache__",
    "artifacts",
    "build",
    "corp-butler",
    "coverage",
    "coverage-current",
    "coverage-detail",
    "coverage-ramp-json",
    "dist",
    "node_modules",
    "playwright-report",
    "test-results",
}
IGNORED_FILE_PATTERNS = (
    ".coverage",
    "*.db",
    "*.db)",
    "cov*.txt",
    "coverage*.txt",
    "err.txt",
    "out.txt",
    "strict*.txt",
    "test-*.wav",
    "test-results.json",
    "tmp_query*",
    "voice-e2e-result.png",
)
IGNORED_PATH_PREFIXES = (
    "MODstore_deploy/data/",
    "MODstore_deploy/library/",
    "MODstore_deploy/modstore_server/backups/",
    "MODstore_deploy/modstore_server/catalog_data/",
    "MODstore_deploy/modstore_server/data/",
    "MODstore_deploy/modstore_server/vector_data/",
    "MODstore_deploy/var/",
    "data/surface_audit/",
)


def _matches(path: str, patterns: Iterable[str]) -> bool:
    name = Path(path).name
    normalized = path.replace("\\", "/")
    for raw in patterns:
        pattern = str(raw or "").strip()
        if not pattern:
            continue
        if pattern.startswith(("./", "/")):
            anchored = pattern[2:] if pattern.startswith("./") else pattern[1:]
            if fnmatch.fnmatch(normalized, anchored):
                return True
            continue
        if "/" in pattern:
            if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(normalized, f"**/{pattern}"):
                return True
        elif fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(normalized, f"**/{pattern}"):
            return True
    return False


def _files(root: Path) -> tuple[list[str], int]:
    included: list[str] = []
    ignored = 0
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        rel_text = rel.as_posix()
        if rel_text.startswith(IGNORED_PATH_PREFIXES) or any(
            part in IGNORED_DIR_NAMES or part.endswith(".egg-info") or part.startswith(".tmp-")
            for part in rel.parts
        ):
            if path.is_file():
                ignored += 1
            continue
        if path.is_file():
            if any(fnmatch.fnmatch(path.name, pattern) for pattern in IGNORED_FILE_PATTERNS):
                ignored += 1
                continue
            included.append(rel.as_posix())
    return sorted(included), ignored


def _cycle_nodes(graph: dict[str, list[str]]) -> set[str]:
    state: dict[str, int] = {}
    stack: list[str] = []
    cycles: set[str] = set()

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for dep in graph[node]:
            if state.get(dep, 0) == 0:
                visit(dep)
            elif state.get(dep) == 1:
                cycles.update(stack[stack.index(dep) :])
        stack.pop()
        state[node] = 2

    for node in graph:
        if state.get(node, 0) == 0:
            visit(node)
    return cycles


def audit(company_root: Path) -> tuple[str, list[str]]:
    yuangon_root = company_root / "yuangon"
    employees: dict[str, dict] = {}
    contract_errors: list[str] = []
    for yaml_path in sorted(yuangon_root.rglob("employee.yaml")):
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        employee_id = str(data.get("id") or "").strip()
        if not employee_id or employee_id in employees:
            contract_errors.append(f"invalid or duplicate id: {yaml_path}")
            continue
        employees[employee_id] = data
        base = yaml_path.parent
        required = {
            "README.md": (base / "README.md").is_file(),
            "runbook.md": (base / "runbook.md").is_file(),
            "prompts/system.md": (base / "prompts" / "system.md").is_file(),
            "capabilities": bool(data.get("capabilities")),
            "skills": bool(data.get("skills")),
            "actions.handlers": bool((data.get("actions") or {}).get("handlers")),
            "examples": bool(data.get("examples")),
        }
        for field, ok in required.items():
            if not ok:
                contract_errors.append(f"{employee_id}: missing {field}")
        for relpath in data.get("skills") or []:
            if not (base / str(relpath)).is_file():
                contract_errors.append(f"{employee_id}: missing skill file {relpath}")

    graph = {
        employee_id: [str(dep) for dep in data.get("depends_on") or []]
        for employee_id, data in employees.items()
    }
    for employee_id, deps in graph.items():
        for dep in deps:
            if dep not in employees:
                contract_errors.append(f"{employee_id}: unknown dependency {dep}")
    cycles = sorted(_cycle_nodes(graph))
    if cycles:
        contract_errors.append("dependency cycles: " + ", ".join(cycles))

    files, ignored_count = _files(company_root)
    writers_by_file: dict[str, list[str]] = defaultdict(list)
    self_conflicts: list[tuple[str, str]] = []
    for relpath in files:
        for employee_id, data in employees.items():
            in_scope = _matches(relpath, data.get("scope_globs") or [])
            forbidden = _matches(relpath, data.get("forbidden_globs") or [])
            if in_scope and forbidden:
                self_conflicts.append((relpath, employee_id))
            if in_scope and not forbidden:
                writers_by_file[relpath].append(employee_id)
    uncovered = [path for path in files if not writers_by_file.get(path)]
    overlaps = [(path, owners) for path, owners in writers_by_file.items() if len(owners) > 1]
    covered = len(files) - len(uncovered)
    coverage = 100.0 if not files else covered * 100.0 / len(files)
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Yuangon 覆盖率与编制契约审计报告",
        "",
        f"> 生成时间（UTC）：`{now}`  ",
        f"> 仓库根：`{company_root}`  ",
        f"> 员工数量：**{len(employees)}**",
        "",
        "## 总览",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
        f"| 扫描文件数 | {len(files)} |",
        f"| 忽略构建/缓存文件数 | {ignored_count} |",
        f"| 有写入责任人 | {covered} |",
        f"| 无写入责任人 | {len(uncovered)} |",
        f"| 覆盖率 | {coverage:.2f}% |",
        f"| 多员工可写 | {len(overlaps)} |",
        f"| scope 被 forbidden 收窄（forbidden 优先） | {len(self_conflicts)} |",
        f"| 编制契约错误 | {len(contract_errors)} |",
        f"| 依赖循环节点 | {len(cycles)} |",
        "",
        "## 编制契约错误",
        "",
    ]
    lines.extend([f"- {item}" for item in contract_errors] or ["- 无"])
    lines.extend(["", "## 无写入责任人（前 200 项）", ""])
    lines.extend([f"- `{path}`" for path in uncovered[:200]] or ["- 无"])
    lines.extend(["", "## 多员工可写（前 200 项）", ""])
    lines.extend(
        [f"- `{path}`：{', '.join(owners)}" for path, owners in overlaps[:200]] or ["- 无"]
    )
    lines.extend(["", "## scope 被 forbidden 收窄（前 200 项）", ""])
    lines.extend(
        [f"- `{path}`：{employee_id}" for path, employee_id in self_conflicts[:200]] or ["- 无"]
    )
    lines.append("")
    return "\n".join(lines), contract_errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    company_root = args.company_root.resolve()
    report, errors = audit(company_root)
    output = args.output or company_root / "yuangon" / "_shared" / "COVERAGE_REPORT.md"
    if not args.check:
        output.write_text(report, encoding="utf-8")
        print(output)
    if errors:
        for error in errors:
            print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
