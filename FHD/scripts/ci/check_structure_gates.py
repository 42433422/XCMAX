#!/usr/bin/env python3
"""XCMAX structure gates — draft (phase-1止血).

Read-only scan of a local XCMAX checkout. Does NOT modify the repo.
Wired into CI via source-governance (structure-gates job).
Ratchet baseline breaches are ERROR (block worsening).
G7/G8/G9 mechanical/noisy/ratio; G3 hardened vs test-fixture escape;
G10 MODstore part ratchet; G11 py>40KB ratchet.

Exit codes:
  0 — no errors (warnings may be printed)
  1 — one or more ERROR findings
  2 — warnings only, and --fail-on-warn was set
  3 — usage / repo path error

Baselines frozen from arch-refactor-phase1 01/02/03 (2026-10-24 Asia/Shanghai).
See ../06-structure-gates.md for rule text.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# --- baselines (do not invent; keep in sync with 06-structure-gates.md) ---
BASELINE = {
    # Tightened 2026-10-25 Asia/Shanghai (arch 18-31 train).
    "mixin_total": 12,
    "mixin_ge_20kb": 0,
    "mixin_ge_15kb": 1,
    "routes_total": 304,
    "routes_top_level": 115,
    "legacy_prod_ref_files": 27,
    "application_ports_py": 1,
    "workflow_ports_py": 1,
    # G7: mechanical (part|mixin)\d+ filenames under FHD/app
    "mechanical_fragments": 0,
    # G8: duplicate basename count for noisy names outside mods/XCAGI (sum of counts)
    "noisy_basename_files": 0,  # app tree: blueprints/parser/mapper/rules/mapping/build_xcemp/convert — expect 0
    # G9 info: application/domain py ratio ceiling (warn if worse)
    "app_domain_ratio_x100": 200,  # debt19: ≤2.00:1
    # G10: MODstore_deploy mechanical part* files (ratchet down; forbid growth)
    "modstore_part_files": 0,
    # G11: repo-wide *.py > 40KB (ratchet; especially tests)
    "py_gt_40kb": 176,
    "py_gt_40kb_testish": 123,
    # debt19 ratchets
    "ports_repo_wide": 15,
    "ports_layer_count": 3,
    "blueprints_py": 40,
    "py_gt_100kb_nontest": 3,
    "fastapi_routes_ports": 0,
}


# G3: no stock fixtures under application after rename to examples/contract_samples
EXEMPT_APP_FIXTURES: set[str] = set()

KB = 1024
GE_20KB = 20 * KB
GE_15KB = 15 * KB


def rel(repo: Path, p: Path) -> str:
    try:
        return str(p.relative_to(repo)).replace("\\", "/")
    except ValueError:
        return str(p)


def find_mixins(app: Path) -> list[Path]:
    return sorted(app.rglob("*mixin*.py"))


def is_route_compat_shim(path: Path) -> bool:
    """兼容 shim：仅通过 sys.modules[__name__] 转发到 domains.*，不计入 G2.2 总数。"""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "sys.modules[__name__]" in text


def find_route_py(routes: Path) -> tuple[list[Path], list[Path], list[Path]]:
    all_py = sorted(p for p in routes.rglob("*.py") if p.is_file())
    top = sorted(p for p in routes.glob("*.py") if p.is_file())
    shims = [p for p in all_py if is_route_compat_shim(p)]
    shim_set = set(shims)
    canonical = [p for p in all_py if p not in shim_set]
    return canonical, top, shims


def count_legacy_prod_refs(repo: Path) -> list[Path]:
    """Approximate 03 methodology: files outside legacy/tests/evals mentioning app.legacy."""
    roots = [repo / "FHD" / "app", repo / "FHD" / "scripts"]
    pat = re.compile(r"app\.legacy")
    hits: list[Path] = []
    skip_parts = {"legacy", "tests", "evals", "test_legacy", ".venv", "node_modules"}
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*.py"):
            parts = set(p.parts)
            # exclude app/legacy tree and tests/evals
            if "legacy" in p.parts and "app" in p.parts:
                # allow only if path contains app/legacy
                try:
                    idx = p.parts.index("legacy")
                    if idx > 0 and p.parts[idx - 1] == "app":
                        continue
                except ValueError:
                    pass
            if any(x in p.parts for x in ("tests", "evals", "test_legacy")):
                continue
            # exclude this gate script and peers that document the pattern
            if p.name in {"check_structure_gates.py", "legacy_usage_report.py"}:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pat.search(text):
                hits.append(p)
    return sorted(set(hits))


def scan_app_fixtures(app_application: Path, repo: Path) -> list[Path]:
    """Filename + content escape hatch detection under application/.

    Forbids pytest-style names and symbols like _SPECIAL_TEST_FIXTURES that
    previously survived a rename-only "fix" of G3.
    """
    bad: list[Path] = []
    if not app_application.is_dir():
        return bad
    forbidden_sym = re.compile(
        r"\b_?SPECIAL_TEST_FIXTURES\b|\bTEST_FIXTURES\s*="
    )
    for p in app_application.rglob("*"):
        if not p.is_file() or p.suffix != ".py":
            continue
        name = p.name
        r = rel(repo, p)
        if r in EXEMPT_APP_FIXTURES:
            continue
        if (
            "fixture" in name.lower()
            or name.startswith("test_")
            or name.endswith("_test.py")
        ):
            bad.append(p)
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if forbidden_sym.search(text):
            bad.append(p)
    return bad


def count_modstore_parts(repo: Path) -> list[Path]:
    roots = list(repo.rglob("MODstore_deploy"))
    pat = re.compile(r"_part_?\d+", re.I)  # mechanical split suffix only
    hits: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*.py"):
            if pat.search(p.name):
                hits.append(p)
    return sorted(set(hits))


def count_py_gt_40kb(repo: Path) -> tuple[list[Path], list[Path]]:
    big: list[Path] = []
    testish: list[Path] = []
    skip = {".venv", "node_modules", "__pycache__", ".git"}
    for p in repo.rglob("*.py"):
        if any(x in p.parts for x in skip):
            continue
        try:
            if p.stat().st_size <= 40_000:
                continue
        except OSError:
            continue
        big.append(p)
        s = str(p).replace("\\", "/").lower()
        if "test" in p.name.lower() or "/tests/" in s or s.startswith("tests/"):
            testish.append(p)
    return sorted(big), sorted(testish)


def new_ports_in_application(repo: Path) -> tuple[int, int, list[str]]:
    """Return (app_ports_count, wf_ports_count, notes)."""
    app_ports = repo / "FHD" / "app" / "application" / "ports"
    wf_ports = repo / "FHD" / "app" / "application" / "workflow" / "ports"
    n_app = len(list(app_ports.glob("*.py"))) if app_ports.is_dir() else 0
    n_wf = len(list(wf_ports.glob("*.py"))) if wf_ports.is_dir() else 0
    return n_app, n_wf, []


def check_tech_stack_doc(repo: Path) -> list[str]:
    p = repo / "FHD" / "docs" / "TECH_STACK.md"
    if not p.is_file():
        return ["TECH_STACK.md missing (G6.1 info)"]
    text = p.read_text(encoding="utf-8", errors="ignore")
    warns = []
    if "灵活部署选项" in text:
        warns.append(
            "TECH_STACK still says「灵活部署选项」— deploy path should defer to ADR-route-a (see 05)"
        )
    if "Kubernetes" in text and "生产编排" in text:
        warns.append(
            "TECH_STACK §4.1 still lists Kubernetes as 生产编排 — mark experimental per 05"
        )
    return warns


def main() -> int:
    ap = argparse.ArgumentParser(description="XCMAX structure gates (draft, read-only)")
    ap.add_argument(
        "--repo",
        default=os.environ.get("XCMAX_REPO", "/workspace/XCMAX"),
        help="Path to XCMAX repo root",
    )
    ap.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="Exit 2 if any WARN (default: warn does not fail)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Print a one-line JSON summary at end",
    )
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    if not (repo / "FHD" / "app").is_dir():
        print(f"ERROR: not an XCMAX root (missing FHD/app): {repo}", file=sys.stderr)
        return 3

    app = repo / "FHD" / "app"
    routes = app / "fastapi_routes"
    errors: list[str] = []
    warns: list[str] = []
    infos: list[str] = []

    # --- G1 mixin ---
    mixins = find_mixins(app)
    ge20 = [p for p in mixins if p.stat().st_size >= GE_20KB]
    ge15 = [p for p in mixins if p.stat().st_size >= GE_15KB]
    infos.append(f"mixin total={len(mixins)} (baseline {BASELINE['mixin_total']})")
    infos.append(f"mixin ≥20KB={len(ge20)} (baseline {BASELINE['mixin_ge_20kb']})")
    infos.append(f"mixin ≥15KB={len(ge15)} (baseline {BASELINE['mixin_ge_15kb']})")
    if len(ge20) > BASELINE["mixin_ge_20kb"]:
        errors.append(
            f"G1.2: mixin ≥20KB count {len(ge20)} > baseline {BASELINE['mixin_ge_20kb']}"
        )
    if len(ge15) > BASELINE["mixin_ge_15kb"]:
        errors.append(
            f"G1.3: mixin ≥15KB count {len(ge15)} > baseline {BASELINE['mixin_ge_15kb']}"
        )
    if len(mixins) > BASELINE["mixin_total"]:
        errors.append(
            f"G1.4: mixin total {len(mixins)} > baseline {BASELINE['mixin_total']}"
        )
    # G1.1 new mixin under application: without git history we only flag if total app mixins
    # exceed a soft expectation — full "new path" needs CI git-diff. Document limitation.
    app_mixins = [p for p in mixins if "application" in p.parts]
    infos.append(
        f"application mixin files={len(app_mixins)} "
        "(G1.1 new-path check needs git diff in CI; draft scans size/count only)"
    )

    # --- G2 routes ---
    if routes.is_dir():
        all_r, top_r, shim_r = find_route_py(routes)
        infos.append(
            f"fastapi_routes total={len(all_r)} top_level={len(top_r)} "
            f"compat_shims={len(shim_r)} "
            f"(baselines {BASELINE['routes_total']}/{BASELINE['routes_top_level']}; "
            f"G2.2 excludes compat shims)"
        )
        if len(all_r) > BASELINE["routes_total"]:
            errors.append(
                f"G2.2: routes total {len(all_r)} > baseline {BASELINE['routes_total']}"
            )
        if len(top_r) > BASELINE["routes_top_level"]:
            errors.append(
                f"G2.3: top-level routes {len(top_r)} > baseline {BASELINE['routes_top_level']}"
            )
        # G2.1 new top-level: without baseline file list, emit info only
        infos.append(
            "G2.1 new top-level .py: wire via git diff vs baseline list in CI "
            f"(current top-level count={len(top_r)})"
        )
    else:
        errors.append("G2: fastapi_routes directory missing")

    # --- G3 fixtures ---
    app_application = app / "application"
    bad_fix = scan_app_fixtures(app_application, repo)
    for p in bad_fix:
        errors.append(f"G3.1: fixture/test name or TEST_FIXTURES symbol under application: {rel(repo, p)}")
    infos.append(
        f"G3 exempt fixtures still present: {len(EXEMPT_APP_FIXTURES)} allowed paths"
    )

    # --- G4 legacy ---
    legacy_refs = count_legacy_prod_refs(repo)
    infos.append(
        f"legacy prod ref files={len(legacy_refs)} "
        f"(baseline {BASELINE['legacy_prod_ref_files']})"
    )
    if len(legacy_refs) > BASELINE["legacy_prod_ref_files"]:
        errors.append(
            f"G4.1: legacy prod refs {len(legacy_refs)} > "
            f"baseline {BASELINE['legacy_prod_ref_files']}"
        )
    # G4.2 legacy_*.py outside app/legacy
    for p in app.rglob("legacy_*.py"):
        if "legacy" in p.parts:
            # inside .../legacy/...
            try:
                if "app" in p.parts and p.parts[p.parts.index("legacy") - 1] == "app":
                    continue
            except (ValueError, IndexError):
                pass
        # also skip if under app/legacy
        if "/app/legacy/" in str(p).replace("\\", "/"):
            continue
        errors.append(f"G4.2: legacy_*.py outside app/legacy: {rel(repo, p)}")

    # --- G5 ports ---
    n_app, n_wf, _ = new_ports_in_application(repo)
    infos.append(
        f"application/ports py={n_app} (baseline {BASELINE['application_ports_py']}); "
        f"workflow/ports py={n_wf} (baseline {BASELINE['workflow_ports_py']})"
    )
    if n_app > BASELINE["application_ports_py"]:
        errors.append(
            f"G5.2: application/ports count {n_app} > "
            f"baseline {BASELINE['application_ports_py']}"
        )
    if n_wf > BASELINE["workflow_ports_py"]:
        errors.append(
            f"G5.2: workflow/ports count {n_wf} > baseline {BASELINE['workflow_ports_py']}"
        )
    domain_ctx_ports = list((app / "domain").glob("*/ports.py")) if (app / "domain").is_dir() else []
    infos.append(
        f"domain/<ctx>/ports.py count={len(domain_ctx_ports)} "
        "(target: grow in phase-2; baseline 0)"
    )

    # --- G7 mechanical fragments (part|mixin digits) ---
    frag_re = re.compile(r"(?:part|mixin)_?\d+", re.I)
    frags = [
        p
        for p in app.rglob("*.py")
        if p.is_file() and frag_re.search(p.name) and "__pycache__" not in p.parts
    ]
    infos.append(
        f"mechanical fragments={len(frags)} "
        f"(baseline {BASELINE['mechanical_fragments']})"
    )
    if len(frags) > BASELINE["mechanical_fragments"]:
        errors.append(
            f"G7: mechanical (part|mixin) digit files {len(frags)} > "
            f"baseline {BASELINE['mechanical_fragments']}: "
            + ", ".join(rel(repo, p) for p in frags[:8])
        )

    # --- G8 noisy duplicate basenames outside mods/XCAGI ---
    noisy = {
        "blueprints.py",
        "parser.py",
        "mapper.py",
        "rules.py",
        "mapping.py",
        "build_xcemp.py",
        "convert.py",
    }
    noisy_hits = []
    for p in app.rglob("*.py"):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        if "mods" in p.parts or "XCAGI" in p.parts:
            continue
        if p.name in noisy:
            noisy_hits.append(p)
    infos.append(
        f"noisy basenames in app (excl mods)={len(noisy_hits)} "
        f"(baseline {BASELINE['noisy_basename_files']})"
    )
    if len(noisy_hits) > BASELINE["noisy_basename_files"]:
        errors.append(
            f"G8: noisy basename files {len(noisy_hits)} > "
            f"baseline {BASELINE['noisy_basename_files']}"
        )

    # --- G9 application/domain ratio ---
    def _count_py(root: Path) -> int:
        if not root.is_dir():
            return 0
        return sum(
            1
            for p in root.rglob("*.py")
            if p.is_file() and "__pycache__" not in p.parts
        )

    n_app = _count_py(app / "application")
    n_dom = _count_py(app / "domain")
    ratio_x100 = int(round((n_app / max(n_dom, 1)) * 100))
    infos.append(
        f"application/domain py={n_app}/{n_dom} ratio={ratio_x100/100:.2f}:1 "
        f"(ceiling {BASELINE['app_domain_ratio_x100']/100:.2f}:1)"
    )
    if ratio_x100 > BASELINE["app_domain_ratio_x100"]:
        warns.append(
            f"G9: application/domain ratio {ratio_x100/100:.2f}:1 > "
            f"ceiling {BASELINE['app_domain_ratio_x100']/100:.2f}:1"
        )

    # domain/<ctx>/ports.py should not shrink below current train
    domain_ctx_ports = (
        list((app / "domain").glob("*/ports.py")) if (app / "domain").is_dir() else []
    )
    if len(domain_ctx_ports) < 7:
        warns.append(
            f"G5.3: domain/<ctx>/ports.py count {len(domain_ctx_ports)} < expected 7"
        )

    # --- G10 MODstore part fragments ---
    mod_parts = count_modstore_parts(repo)
    infos.append(
        f"MODstore part files={len(mod_parts)} (baseline {BASELINE['modstore_part_files']})"
    )
    if len(mod_parts) > BASELINE["modstore_part_files"]:
        errors.append(
            f"G10: MODstore part files {len(mod_parts)} > "
            f"baseline {BASELINE['modstore_part_files']}"
        )

    # --- G11 py > 40KB ratchet ---
    big_py, big_test = count_py_gt_40kb(repo)
    infos.append(
        f"py>40KB={len(big_py)} testish={len(big_test)} "
        f"(baselines {BASELINE['py_gt_40kb']}/{BASELINE['py_gt_40kb_testish']})"
    )
    if len(big_py) > BASELINE["py_gt_40kb"]:
        errors.append(
            f"G11: py>40KB {len(big_py)} > baseline {BASELINE['py_gt_40kb']}"
        )
    if len(big_test) > BASELINE["py_gt_40kb_testish"]:
        errors.append(
            f"G11: py>40KB testish {len(big_test)} > "
            f"baseline {BASELINE['py_gt_40kb_testish']}"
        )


    # --- G12 debt19 ports / layers / blueprints / giants / domain-services ---
    ports_all = [
        p
        for p in repo.rglob("ports.py")
        if ".git" not in p.parts and "node_modules" not in p.parts and ".venv" not in p.parts
    ]
    infos.append(
        f"ports_repo_wide={len(ports_all)} (baseline {BASELINE.get('ports_repo_wide', 15)})"
    )
    if len(ports_all) > BASELINE.get("ports_repo_wide", 15):
        errors.append(
            f"G12: ports.py count {len(ports_all)} > baseline {BASELINE.get('ports_repo_wide', 15)}"
        )
    layer_names = {
        "application",
        "domain",
        "infrastructure",
        "fastapi_routes",
        "legacy",
        "mod_sdk",
        "services",
    }
    layers = set()
    for port_path in ports_all:
        for name in layer_names:
            if name in port_path.parts:
                layers.add(name)
    infos.append(f"ports_layers={sorted(layers)} count={len(layers)}")
    if len(layers) > BASELINE.get("ports_layer_count", 3):
        errors.append(
            f"G12: ports layers {len(layers)} > {BASELINE.get('ports_layer_count', 3)}: {sorted(layers)}"
        )
    fr_ports = [port_path for port_path in ports_all if "fastapi_routes" in port_path.parts]
    if len(fr_ports) > BASELINE.get("fastapi_routes_ports", 0):
        errors.append(f"G12: fastapi_routes ports {len(fr_ports)} > 0")
    if (app / "domain" / "services").exists():
        errors.append("G12: domain/services directory must not exist")
    bps = [
        port_path
        for port_path in repo.rglob("blueprints.py")
        if ".git" not in port_path.parts and "node_modules" not in port_path.parts
    ]
    infos.append(
        f"blueprints.py={len(bps)} (baseline {BASELINE.get('blueprints_py', 40)})"
    )
    if len(bps) > BASELINE.get("blueprints_py", 40):
        errors.append(
            f"G12: blueprints.py {len(bps)} > baseline {BASELINE.get('blueprints_py', 40)}"
        )
    big100 = []
    for py_path in repo.rglob("*.py"):
        if any(x in py_path.parts for x in (".git", "node_modules", "__pycache__", ".venv")):
            continue
        # first-party ratchet: skip vendored LangGraph + eval harness
        if any("xcagi_langgraph" in part for part in py_path.parts) or "evals" in py_path.parts:
            continue
        try:
            sz = py_path.stat().st_size
        except OSError:
            continue
        if sz <= 100_000:
            continue
        s = str(py_path).replace("\\", "/").lower()
        if "test" in py_path.name.lower() or "/tests/" in s:
            continue
        big100.append(py_path)
    infos.append(
        f"py>100KB nontest={len(big100)} (baseline {BASELINE.get('py_gt_100kb_nontest', 0)})"
    )
    if len(big100) > BASELINE.get("py_gt_100kb_nontest", 0):
        errors.append(
            f"G12: py>100KB nontest {len(big100)} > baseline {BASELINE.get('py_gt_100kb_nontest', 0)}"
        )

    # --- G6 docs ---
    for w in check_tech_stack_doc(repo):
        warns.append(f"G6.1: {w}")

    # --- print ---
    for line in infos:
        print(f"INFO  {line}")
    for line in warns:
        print(f"WARN  {line}")
    for line in errors:
        print(f"ERROR {line}")

    summary = {
        "repo": str(repo),
        "errors": len(errors),
        "warns": len(warns),
        "infos": len(infos),
    }
    if args.json:
        import json

        print(json.dumps(summary, ensure_ascii=False))

    print(
        f"--- summary: errors={len(errors)} warns={len(warns)} "
        f"(fail-on-warn={args.fail_on_warn}) ---"
    )

    if errors:
        return 1
    if warns and args.fail_on_warn:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
