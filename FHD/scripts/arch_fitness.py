#!/usr/bin/env python3
"""
Architecture Fitness Function

Validates architectural invariants that should hold true across all commits.
Run: python scripts/arch_fitness.py
Exit code: 0 = all checks pass, 1 = violations found

File length is advisory only: files above the soft cap need an approved, expiring entry in
``arch_line_exceptions.json`` to silence the warning, and never fail the gate. Coupling is what
blocks: import-time cycles, cross-layer edges, ``_facade()`` late-binding back into a facade,
numbered fragment modules, sibling-mixin method shadowing, and ratcheted fan-out / public API /
deferred-cycle metrics (``arch_metrics_baseline.json``).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tomllib
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import arch_graph  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"
MODSTORE_SERVER_DIR = (
    REPO_ROOT.parent / "成都修茈科技有限公司" / "MODstore_deploy" / "modstore_server"
)

MAX_FILE_LINES = 800
FAN_OUT_CAP = 25
PUBLIC_API_CAP = 60
SCRIPTS_DIR = Path(__file__).resolve().parent
BASELINE_FILE = SCRIPTS_DIR / "arch_fitness_baseline.txt"
METRICS_BASELINE_FILE = SCRIPTS_DIR / "arch_metrics_baseline.json"
LINE_EXCEPTIONS_FILE = SCRIPTS_DIR / "arch_line_exceptions.json"

# target-structure.md: routes -> application -> domain; infrastructure -> ports + domain.
LAYER_FORBIDDEN = {
    "domain": ("application", "infrastructure", "interface"),
    "ports": ("application", "infrastructure", "interface"),
    "application": ("infrastructure", "interface"),
    "infrastructure": ("interface",),
    "interface": ("infrastructure",),
}


def _packages() -> dict[str, tuple[Path, Path, dict[str, str]]]:
    """package -> (import root, path root for report keys, layer prefixes)."""
    return {
        "app": (
            APP_DIR.parent,
            REPO_ROOT,
            {
                "app.domain": "domain",
                "app.application.ports": "ports",
                "app.application": "application",
                "app.infrastructure": "infrastructure",
                "app.fastapi_routes": "interface",
                "app.routes": "interface",
            },
        ),
        "modstore_server": (
            MODSTORE_SERVER_DIR.parent,
            REPO_ROOT.parent,
            {
                "modstore_server.domain": "domain",
                "modstore_server.application": "application",
                "modstore_server.infrastructure": "infrastructure",
                "modstore_server.api": "interface",
            },
        ),
    }


GRAPH_SKIP = ("workbench_script_runs",)

VIOLATIONS: list[str] = []
METRIC_REGRESSIONS: list[str] = []
WARNINGS: list[str] = []
_GRAPHS: dict[str, arch_graph.Graph] = {}


def _violation_key(violation: str) -> str:
    """基线键：`[check-type] path`（不含行号与行数后缀）。"""
    key = violation.split(" — ", 1)[0].strip() if " — " in violation else violation.strip()
    if "] " in key:
        prefix, path_part = key.split("] ", 1)
        path_part = path_part.replace("\\", "/")
        return f"{prefix}] {path_part}"
    return key.replace("\\", "/")


def _load_baseline_keys() -> set[str]:
    if not BASELINE_FILE.is_file():
        return set()
    keys: set[str] = set()
    for raw in BASELINE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keys.add(_violation_key(line))
    return keys


def _is_excluded_path(path: Path) -> bool:
    parts = path.parts
    if "__pycache__" in parts:
        return True
    if any(".v1_backup" in p for p in parts):
        return True
    name = path.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return False


def _count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
    except (OSError, UnicodeDecodeError):
        return 0


def _graphs() -> dict[str, arch_graph.Graph]:
    if not _GRAPHS:
        for package, (root, _rel_root, _layers) in _packages().items():
            if (root / package).is_dir():
                _GRAPHS[package] = arch_graph.load_graph(root, package, skip=GRAPH_SKIP)
            else:
                print(f"  [skip] {package} not found under {root}")
    return _GRAPHS


def _rel(package: str, module: str) -> str:
    _root, rel_root, _layers = _packages()[package]
    return _GRAPHS[package].modules[module].path.relative_to(rel_root).as_posix()


def check_no_v1_backup_files() -> None:
    for path in APP_DIR.rglob("*.v1_backup"):
        rel = path.relative_to(REPO_ROOT)
        VIOLATIONS.append(f"[v1_backup] {rel} — backup file must be removed")


def check_routes_not_import_services() -> None:
    routes_dirs = [APP_DIR / "routes", APP_DIR / "fastapi_routes"]
    for routes_dir in routes_dirs:
        if not routes_dir.is_dir():
            continue
        for py in routes_dir.rglob("*.py"):
            rel = py.relative_to(REPO_ROOT)
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module and "app.services" in node.module:
                    names = ", ".join(a.name for a in node.names)
                    VIOLATIONS.append(
                        f"[routes->services] {rel}:{node.lineno} — "
                        f"from {node.module} import {names} "
                        f"(routes should use app.application, not app.services)"
                    )


def _load_line_exceptions() -> dict[str, dict[str, str]]:
    if not LINE_EXCEPTIONS_FILE.is_file():
        return {}
    data = json.loads(LINE_EXCEPTIONS_FILE.read_text(encoding="utf-8"))
    return dict(data.get("exceptions", {}))


def check_file_length_advisory() -> None:
    """Soft cap: never blocks. Approved exceptions silence the warning until they expire."""
    exceptions = _load_line_exceptions()
    today = date.today().isoformat()
    roots = [(APP_DIR, REPO_ROOT), (MODSTORE_SERVER_DIR, REPO_ROOT.parent)]
    for base, rel_root in roots:
        if not base.is_dir():
            continue
        for py in base.rglob("*.py"):
            if _is_excluded_path(py):
                continue
            line_count = _count_lines(py)
            if line_count <= MAX_FILE_LINES:
                continue
            rel = py.relative_to(rel_root).as_posix()
            entry = exceptions.get(rel)
            if entry and str(entry.get("expires", "")) >= today:
                continue
            state = "exception expired" if entry else "no approved exception"
            WARNINGS.append(
                f"[giant-file] {rel} — {line_count} lines > soft cap {MAX_FILE_LINES} ({state}; "
                f"split along a domain boundary or register in {LINE_EXCEPTIONS_FILE.name})"
            )


def check_legacy_boundary() -> None:
    """legacy_* / *_compat / compat_* 文件必须收容在 app/legacy/ 下，禁止散落。

    P1-4 双轨治理：``*_compat`` / ``compat_*`` 命名的过渡实现与 ``legacy_*`` 一样，
    必须统一收容到 ``app/legacy/``，防止同一功能双套实现散落各子目录。
    """
    legacy_root = APP_DIR / "legacy"
    stable_compat_roots = (APP_DIR / "mod_sdk",)
    patterns = ("legacy_*.py", "*_compat.py", "compat_*.py")
    for glob in patterns:
        for py in APP_DIR.rglob(glob):
            if _is_excluded_path(py):
                continue
            if any(py.is_relative_to(root) for root in stable_compat_roots):
                # ``mod_sdk`` is the public compatibility contract for bundled
                # Mods, not a legacy implementation directory.
                continue
            try:
                py.relative_to(legacy_root)
                continue
            except ValueError:
                pass
            rel = py.relative_to(REPO_ROOT)
            VIOLATIONS.append(
                f"[legacy-boundary] {rel} — legacy_*/compat_* file must live under app/legacy/"
            )


def check_import_cycles() -> None:
    for package, graph in _graphs().items():
        for src, dst in arch_graph.cycle_edges(graph, graph.import_time):
            VIOLATIONS.append(
                f"[import-cycle] {_rel(package, src)} -> {_rel(package, dst)} — "
                "module-level imports form a cycle"
            )


def check_cross_layer() -> None:
    for package, graph in _graphs().items():
        layers = _packages()[package][2]
        for src, dst in arch_graph.cross_layer_edges(graph, layers, LAYER_FORBIDDEN):
            VIOLATIONS.append(
                f"[cross-layer] {_rel(package, src)} -> {_rel(package, dst)} — "
                f"{arch_graph.layer_of(src, layers)} must not depend on "
                f"{arch_graph.layer_of(dst, layers)}"
            )


def check_module_shape() -> None:
    for package, graph in _graphs().items():
        for name, mod in graph.modules.items():
            if _is_excluded_path(mod.path):
                continue
            rel = _rel(package, name)
            if arch_graph.defines_facade_hook(mod):
                VIOLATIONS.append(
                    f"[facade-late-binding] {rel} — _facade() resolves names from another module "
                    "at runtime; import them statically or keep them in this module"
                )
            if arch_graph.is_fragment_name(mod.path):
                VIOLATIONS.append(
                    f"[fragment-name] {rel} — numbered/merged fragment; name modules by "
                    "responsibility"
                )
        for module, cls, method in arch_graph.mixin_collisions(graph):
            VIOLATIONS.append(
                f"[mixin-collision] {_rel(package, module)}::{cls}.{method} — sibling bases "
                "both implement this method; MRO silently picks one"
            )


def mypy_ignored_modules(import_root: Path, package: str) -> int:
    """Modules of ``package`` whose type errors pyproject.toml hides (ignore_errors / exclude)."""
    pyproject = import_root / "pyproject.toml"
    if not pyproject.is_file():
        return 0
    cfg = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("tool", {}).get("mypy", {})
    count = sum(1 for pattern in cfg.get("exclude", []) if package in pattern)
    for override in cfg.get("overrides", []):
        if not override.get("ignore_errors"):
            continue
        modules = override.get("module", [])
        modules = [modules] if isinstance(modules, str) else modules
        count += sum(1 for m in modules if m == package or m.startswith(package + "."))
    return count


def collect_metrics() -> dict[str, dict]:
    metrics: dict[str, dict] = {}
    roots = {package: spec[0] for package, spec in _packages().items()}
    for package, graph in _graphs().items():
        components = arch_graph.strongly_connected(sorted(graph.modules), graph.all_edges)
        fan_out = {}
        public_api = {}
        mypy_disables = 0
        for name, mod in graph.modules.items():
            rel = _rel(package, name)
            if graph.fan_out(name) > FAN_OUT_CAP:
                fan_out[rel] = graph.fan_out(name)
            api = arch_graph.public_api_count(mod)
            if api > PUBLIC_API_CAP:
                public_api[rel] = api
            mypy_disables += arch_graph.mypy_file_disables(mod)
        metrics[package] = {
            "deferred_cycle_modules": sum(len(c) for c in components),
            "largest_deferred_cycle": max((len(c) for c in components), default=0),
            "mypy_file_disables": mypy_disables,
            "mypy_ignored_modules": mypy_ignored_modules(roots[package], package),
            "fan_out_over_cap": dict(sorted(fan_out.items())),
            "public_api_over_cap": dict(sorted(public_api.items())),
        }
    return metrics


def _load_metrics_baseline() -> dict:
    if not METRICS_BASELINE_FILE.is_file():
        return {}
    return dict(json.loads(METRICS_BASELINE_FILE.read_text(encoding="utf-8")).get("packages", {}))


def metric_regressions(current: dict[str, dict], baseline: dict[str, dict]) -> list[str]:
    out = []
    for package, values in current.items():
        base = baseline.get(package)
        if base is None:
            continue
        for key in (
            "deferred_cycle_modules",
            "largest_deferred_cycle",
            "mypy_file_disables",
            "mypy_ignored_modules",
        ):
            if values[key] > base.get(key, 0):
                out.append(f"[metric] {package}.{key} {values[key]} > baseline {base.get(key, 0)}")
        for key, cap in (("fan_out_over_cap", FAN_OUT_CAP), ("public_api_over_cap", PUBLIC_API_CAP)):
            for rel, value in values[key].items():
                allowed = base.get(key, {}).get(rel, cap)
                if value > allowed:
                    out.append(f"[metric] {key} {rel} {value} > allowed {allowed}")
    return out


def print_metric_report(current: dict[str, dict]) -> None:
    for package, graph in _graphs().items():
        values = current[package]
        fan_in = sorted(graph.fan_in().items(), key=lambda kv: -kv[1])[:3]
        fan_out = sorted(((graph.fan_out(m), m) for m in graph.modules), reverse=True)[:3]
        print(
            f"  [metrics] {package}: modules={len(graph.modules)} "
            f"import-time-cycle-edges={len(arch_graph.cycle_edges(graph, graph.import_time))} "
            f"deferred-cycle-modules={values['deferred_cycle_modules']} "
            f"(largest {values['largest_deferred_cycle']}) "
            f"mypy-file-disables={values['mypy_file_disables']} "
            f"mypy-ignored-modules={values['mypy_ignored_modules']}"
        )
        print(f"    fan-in top: {', '.join(f'{m}={n}' for m, n in fan_in)}")
        print(f"    fan-out top: {', '.join(f'{m}={n}' for n, m in fan_out)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Replace the debt baselines with the exact current violation keys and metrics.",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Required with --update-baseline when any ratcheted metric increases.",
    )
    args = parser.parse_args(argv)
    print("=== Architecture Fitness Check ===\n")

    VIOLATIONS.clear()
    WARNINGS.clear()
    METRIC_REGRESSIONS.clear()
    _GRAPHS.clear()
    check_no_v1_backup_files()
    check_routes_not_import_services()
    check_file_length_advisory()
    check_legacy_boundary()
    check_import_cycles()
    check_cross_layer()
    check_module_shape()
    metrics = collect_metrics()
    METRIC_REGRESSIONS.extend(metric_regressions(metrics, _load_metrics_baseline()))

    for warning in WARNINGS:
        print(f"  WARNING: {warning}")
    print_metric_report(metrics)

    if args.update_baseline:
        if METRIC_REGRESSIONS and not args.reason.strip():
            print("Refusing to raise ratcheted metrics without --reason:")
            for regression in METRIC_REGRESSIONS:
                print(f"  {regression}")
            return 2
        keys = sorted({_violation_key(v) for v in VIOLATIONS})
        body = (
            "# Architecture debt snapshot. New keys fail the gate; remove keys as debt is paid.\n"
            + "\n".join(keys)
            + "\n"
        )
        BASELINE_FILE.write_text(body, encoding="utf-8")
        previous = (
            json.loads(METRICS_BASELINE_FILE.read_text(encoding="utf-8"))
            if METRICS_BASELINE_FILE.is_file()
            else {}
        )
        raises = list(previous.get("raised", []))
        if METRIC_REGRESSIONS:
            raises.append({"date": date.today().isoformat(), "reason": args.reason.strip()})
        payload = {
            "_note": "Ratchet: values may only fall. Raising one requires --update-baseline "
            "--reason and is recorded in 'raised'.",
            "packages": metrics,
            "raised": raises,
        }
        METRICS_BASELINE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Updated {BASELINE_FILE.name}: {len(keys)} key(s); {METRICS_BASELINE_FILE.name}.")
        return 0

    baseline = _load_baseline_keys()
    new_violations = [v for v in VIOLATIONS if _violation_key(v) not in baseline]
    baselined = len(VIOLATIONS) - len(new_violations)

    if baselined:
        print(
            f"  [baseline] {baselined} known violation(s) suppressed (see arch_fitness_baseline.txt)"
        )

    failures = new_violations + METRIC_REGRESSIONS
    if failures:
        print(f"FAIL {len(failures)} new violation(s) (total found {len(VIOLATIONS)}):\n")
        for v in failures:
            print(f"  {v}")
        print()
        return 1

    if VIOLATIONS:
        print("PASS: no new violations (baseline only).")
        return 0

    print("PASS: all architecture fitness checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
