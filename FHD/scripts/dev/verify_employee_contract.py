#!/usr/bin/env python3
"""员工包契约三方一致性校验（日更 CI gate）。

检查每个员工包：
1. manifest.depends_on == manifest.employee_config_v2.collaboration.depends_on
2. manifest.actions.handlers 在 backend/employees/*.py 的 _DISPATCH 中均有对应字面量
3. yuangon/<area>/<id>/employee.yaml 存在
4. yuangon employee.yaml.depends_on == manifest.depends_on
5. yuangon employee.yaml.actions.handlers == manifest.actions.handlers
6. scope_globs 包含 yuangon mirror glob（yuangon/<area>/<id>/**）

退出码：0 = 全通过，1 = 有 warning，2 = 有 ERROR

运行：python FHD/scripts/dev/verify_employee_contract.py [--strict]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

REPO = Path(__file__).resolve().parents[3]
EMP_ROOT = REPO / "FHD" / "mods" / "_employees"
YUANGON_ROOT = REPO / "成都修茈科技有限公司" / "yuangon"

WARN = "WARN"
ERROR = "ERROR"
OK = "OK"


def _load_yaml_depends(yaml_path: Path) -> list[str]:
    if not yaml_path.exists():
        return []
    if _HAS_YAML:
        try:
            data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                deps = data.get("depends_on", [])
                return [str(x).strip() for x in deps if str(x).strip()] if isinstance(deps, list) else []
        except Exception:
            pass
    # Fallback: regex parse
    content = yaml_path.read_text(encoding="utf-8")
    deps = re.findall(r"^\s*-\s+(.+)$", content[content.find("depends_on:"):].split("\n\n")[0], re.MULTILINE)
    return [d.strip() for d in deps if d.strip() and not d.startswith("#")]


def _load_yaml_handlers(yaml_path: Path) -> list[str]:
    if not yaml_path.exists():
        return []
    if _HAS_YAML:
        try:
            data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                actions = data.get("actions", {})
                if isinstance(actions, dict):
                    h = actions.get("handlers", [])
                    return [str(x).strip() for x in h if str(x).strip()] if isinstance(h, list) else []
        except Exception:
            pass
    return []


def _backend_dispatch_keys(emp_dir: Path, pkg_id: str) -> set[str]:
    """Extract handler keys from backend/employees/*.py _DISPATCH dict."""
    backend = emp_dir / "backend" / "employees"
    if not backend.exists():
        return set()
    keys: set[str] = set()
    slug = pkg_id.replace("-", "_")
    # Try the expected filename first, then all .py files
    candidates = list(backend.glob(f"{slug}.py")) + list(backend.glob("*.py"))
    for py_file in candidates:
        content = py_file.read_text(encoding="utf-8", errors="replace")
        # Match 'echo' / "llm_md" etc inside _DISPATCH = { ... }
        dispatch_match = re.search(r"_DISPATCH\s*=\s*\{(.+?)\}", content, re.DOTALL)
        if dispatch_match:
            for m in re.finditer(r"['\"](\w+)['\"]", dispatch_match.group(1)):
                keys.add(m.group(1))
    return keys


def check_employee(emp_dir: Path) -> tuple[str, list[tuple[str, str]]]:
    mf_path = emp_dir / "manifest.json"
    if not mf_path.exists():
        return emp_dir.name, [(WARN, "manifest.json not found")]

    try:
        mf = json.loads(mf_path.read_text())
    except Exception as e:
        return emp_dir.name, [(ERROR, f"manifest.json parse error: {e}")]

    pkg_id = mf.get("id", emp_dir.name)
    v2 = mf.get("employee_config_v2", {})
    identity = v2.get("identity", {})
    area = identity.get("area", "")
    wp = v2.get("workspace_policy", {})
    scope_globs: list = wp.get("scope_globs", [])
    collab = v2.get("collaboration", {})
    actions = v2.get("actions", {})

    root_depends: list = mf.get("depends_on", [])
    collab_depends: list = collab.get("depends_on", []) if isinstance(collab, dict) else []
    handlers: list = actions.get("handlers", [])

    issues: list[tuple[str, str]] = []

    # Check 1: depends_on consistency
    if sorted(root_depends) != sorted(collab_depends):
        issues.append((ERROR, f"depends_on mismatch: root={root_depends} vs collaboration={collab_depends}"))

    # Check 2: handlers in _DISPATCH
    if handlers:
        dispatch_keys = _backend_dispatch_keys(emp_dir, pkg_id)
        if dispatch_keys:
            for h in handlers:
                if h not in dispatch_keys:
                    issues.append((WARN, f"handler '{h}' declared in manifest but not found in _DISPATCH"))
        else:
            issues.append((WARN, "no _DISPATCH found in backend/employees/*.py – cannot verify handlers"))

    # Check 3: yuangon yaml exists
    if area:
        yg_yaml = YUANGON_ROOT / area / pkg_id / "employee.yaml"
        if not yg_yaml.exists():
            issues.append((ERROR, f"yuangon/{area}/{pkg_id}/employee.yaml missing"))
        else:
            # Check 4: yuangon depends_on matches
            yg_depends = _load_yaml_depends(yg_yaml)
            if yg_depends and sorted(yg_depends) != sorted(root_depends):
                issues.append((WARN, f"yuangon depends_on {yg_depends} != manifest {root_depends}"))

            # Check 5: yuangon handlers match
            yg_handlers = _load_yaml_handlers(yg_yaml)
            if yg_handlers and sorted(yg_handlers) != sorted(handlers):
                issues.append((WARN, f"yuangon handlers {yg_handlers} != manifest {handlers}"))

        # Check 6: yuangon mirror glob in scope_globs
        expected_mirror = f"yuangon/{area}/{pkg_id}/**"
        has_mirror = expected_mirror in scope_globs or any(
            "yuangon" in g and pkg_id in g for g in scope_globs
        )
        if not has_mirror:
            issues.append((WARN, f"scope_globs missing yuangon mirror: {expected_mirror}"))

    return pkg_id, issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="Treat WARN as ERROR (exit 2 on any issue)")
    args = parser.parse_args()

    all_issues: dict[str, list[tuple[str, str]]] = {}
    for d in sorted(EMP_ROOT.iterdir()):
        if not d.is_dir():
            continue
        pkg_id, issues = check_employee(d)
        if issues:
            all_issues[pkg_id] = issues

    if not all_issues:
        print("✅  All employee contracts verified — no issues found.")
        return 0

    error_count = warn_count = 0
    for pkg_id, issues in all_issues.items():
        for level, msg in issues:
            if level == ERROR:
                error_count += 1
            else:
                warn_count += 1
            print(f"[{level}] {pkg_id}: {msg}")

    print(f"\nSummary: {error_count} ERROR(s), {warn_count} WARN(s) across {len(all_issues)} employee(s)")

    if error_count > 0:
        return 2
    if args.strict and warn_count > 0:
        return 2
    return 1 if warn_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
