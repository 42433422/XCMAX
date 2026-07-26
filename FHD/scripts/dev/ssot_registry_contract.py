#!/usr/bin/env python3
"""Cross-check the machine and human SSOT registries.

``config/ssot.yaml`` is the executable registry used by ``ssot_cli.py``.
``docs/SSOT_INDEX.md`` is the human-facing registry.  A row in the Markdown
table binds to an executable domain through its ``执行注册名`` cell.  This
module makes that projection enforceable instead of letting the two registries
drift independently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent
REGISTRY_PATH = FHD_ROOT / "config" / "ssot.yaml"
INDEX_PATH = FHD_ROOT / "docs" / "SSOT_INDEX.md"

_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_CODE_RE = re.compile(r"`([^`]+)`")
_EMPTY_BINDINGS = {"", "-", "—", "–", "n/a", "N/A"}


@dataclass(frozen=True)
class IndexBinding:
    index_domain: str
    executable_domain: str
    ssot_path: Path
    line_number: int


def _resolved_registry_path(raw: str, repo_root: Path = REPO_ROOT) -> Path:
    path_text = raw.split("#", 1)[0].strip()
    return (repo_root / path_text).resolve()


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _resolved_index_path(index_path: Path, cell: str) -> Path | None:
    match = _LINK_RE.search(cell)
    raw = match.group(1).strip() if match else cell.strip()
    if not raw or raw in _EMPTY_BINDINGS or "://" in raw:
        return None
    return (index_path.parent / raw.split("#", 1)[0]).resolve()


def _binding_name(cell: str) -> str:
    match = _CODE_RE.fullmatch(cell.strip())
    raw = match.group(1) if match else cell.strip()
    return "" if raw in _EMPTY_BINDINGS else raw


def parse_index_bindings(index_path: Path = INDEX_PATH) -> tuple[list[IndexBinding], list[str]]:
    """Parse executable-domain bindings from the primary registration table."""
    if not index_path.is_file():
        return [], [f"human registry missing: {index_path}"]

    bindings: list[IndexBinding] = []
    errors: list[str] = []
    in_table = False
    for line_number, line in enumerate(index_path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped == "## 领域 SSOT 登记表":
            in_table = True
            continue
        if in_table and stripped.startswith("## "):
            break
        if not in_table or not stripped.startswith("|"):
            continue

        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or cells[0] == "领域" or set(cells[0]) <= {"-", ":"}:
            continue
        if len(cells) < 4:
            errors.append(
                f"{index_path.name}:{line_number}: registration row lacks 执行注册名 column"
            )
            continue

        executable_domain = _binding_name(cells[3])
        if not executable_domain:
            continue
        resolved = _resolved_index_path(index_path, cells[1])
        if resolved is None:
            errors.append(
                f"{index_path.name}:{line_number}: {executable_domain} has no local SSOT path"
            )
            continue
        bindings.append(
            IndexBinding(
                index_domain=cells[0],
                executable_domain=executable_domain,
                ssot_path=resolved,
                line_number=line_number,
            )
        )
    return bindings, errors


def validate_registry_contract(
    registry_path: Path = REGISTRY_PATH,
    index_path: Path = INDEX_PATH,
) -> list[str]:
    """Return contract violations; an empty list means the registries agree."""
    if not registry_path.is_file():
        return [f"machine registry missing: {registry_path}"]
    repo_root = registry_path.resolve().parents[2]

    try:
        raw: Any = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"cannot parse machine registry: {exc}"]

    domains = raw.get("domains") if isinstance(raw, dict) else None
    if not isinstance(domains, list):
        return ["machine registry must contain a domains list"]

    errors: list[str] = []
    machine: dict[str, Path] = {}
    for position, item in enumerate(domains, 1):
        if not isinstance(item, dict):
            errors.append(f"machine registry domains[{position}] is not a mapping")
            continue
        name = str(item.get("name") or "").strip()
        ssot = str(item.get("ssot") or "").strip()
        if not name or not ssot:
            errors.append(f"machine registry domains[{position}] requires name and ssot")
            continue
        if name in machine:
            errors.append(f"machine registry duplicates domain: {name}")
            continue
        machine[name] = _resolved_registry_path(ssot, repo_root)

    bindings, index_errors = parse_index_bindings(index_path)
    errors.extend(index_errors)
    human: dict[str, IndexBinding] = {}
    for binding in bindings:
        previous = human.get(binding.executable_domain)
        if previous is not None:
            errors.append(
                "human registry duplicates executable domain "
                f"{binding.executable_domain}: lines {previous.line_number}, {binding.line_number}"
            )
            continue
        human[binding.executable_domain] = binding

    for name, machine_path in sorted(machine.items()):
        binding = human.get(name)
        if binding is None:
            errors.append(f"machine domain {name} has no SSOT_INDEX binding")
            continue
        if binding.ssot_path != machine_path:
            errors.append(
                f"{name}: registry path mismatch: "
                f"ssot.yaml={_display_path(machine_path, repo_root)} "
                f"SSOT_INDEX={_display_path(binding.ssot_path, repo_root)}"
            )

    for name, binding in sorted(human.items()):
        if name not in machine:
            errors.append(
                f"SSOT_INDEX line {binding.line_number} binds unknown machine domain {name}"
            )

    return errors


def main() -> int:
    errors = validate_registry_contract()
    if errors:
        print("SSOT 双注册表互校失败:")
        for error in errors:
            print(f"  - {error}")
        return 1
    bindings, _ = parse_index_bindings()
    print(f"SSOT 双注册表一致: {len(bindings)} 个执行域已逐项绑定。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
