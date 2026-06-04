#!/usr/bin/env python3
"""Split multi-domain tests/routes/test_routes_*.py into test_<domain>_routes.py files.

Heuristic: parse header comment ``Phase N: a, b, c`` or filename tokens after test_routes_.
Does not merge bodies automatically — use --dry-run first, then --apply for file moves.

Pilot (2026-06): prefer small ramp-migrated files; large files need manual fixture extraction (T16).

Usage:
  python FHD/scripts/dev/split_routes_tests.py --list
  python FHD/scripts/dev/split_routes_tests.py --dry-run tests/routes/test_routes_health_k8s_template_api_mocked_isolated_from_pha.py
  python FHD/scripts/dev/split_routes_tests.py --apply --domains health_k8s,template_api <file>
"""

from __future__ import annotations

import argparse
import re
import shutil
import textwrap
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
ROUTES_DIR = FHD_ROOT / "tests" / "routes"
DEPRECATED = "# DEPRECATED (migrated): was {name}\n"
HEADER_DOMAINS = re.compile(
    r"Phase\s+\d+:\s*([^\n]+)",
    re.IGNORECASE,
)
TEST_ROUTES_PREFIX = re.compile(r"^test_routes_(.+)\.py$")


def _routes_files() -> list[Path]:
    return sorted(ROUTES_DIR.glob("test_routes_*.py"))


def _domains_from_header(text: str) -> list[str]:
    m = HEADER_DOMAINS.search(text)
    if not m:
        return []
    raw = m.group(1).split("(")[0]
    parts = re.split(r"[,;]\s*|\s+and\s+", raw)
    out: list[str] = []
    for p in parts:
        token = re.sub(r"\s*\(.*$", "", p.strip()).strip().lower()
        token = re.sub(r"[^a-z0-9_]+", "_", token)
        token = token.strip("_")
        if token and token not in ("mocked", "isolated", "from", "gaps"):
            out.append(token)
    return out


def _domains_from_filename(path: Path) -> list[str]:
    m = TEST_ROUTES_PREFIX.match(path.name)
    if not m:
        return []
    slug = m.group(1)
    stop = {"mocked", "isolated", "from", "pha", "gaps", "test", "routes", "fastapi", "more", "low", "coverage", "high", "miss", "modules", "i", "o", "r", "s", "60"}
    tokens: list[str] = []
    for part in slug.split("_"):
        if part in stop or len(part) <= 1:
            continue
        tokens.append(part)
    return tokens[:8]


def infer_domains(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    domains = _domains_from_header(text)
    if not domains:
        domains = _domains_from_filename(path)
    return domains


def target_name(domain: str) -> str:
    d = domain.strip("_")
    if d.endswith("_routes"):
        return f"test_{d}.py"
    return f"test_{d}_routes.py"


def list_candidates() -> None:
    for p in _routes_files():
        domains = infer_domains(p)
        targets = [target_name(d) for d in domains] if domains else ["(manual)"]
        print(f"{p.name}\t{len(p.read_text().splitlines())} lines\t-> {', '.join(targets)}")


def apply_split(
    source: Path,
    domains: list[str],
    *,
    dry_run: bool,
) -> None:
    if not source.is_file():
        raise SystemExit(f"Not found: {source}")
    body = source.read_text(encoding="utf-8")
    if len(domains) < 2:
        print(f"Skip {source.name}: need >=2 domains (got {domains!r}); use manual split.")
        return

    print(
        textwrap.dedent(
            f"""
            Manual step required for {source.name}:
              Domains: {domains}
              Suggested targets: {[target_name(d) for d in domains]}
              Copy test functions + fixtures per domain; leave stub in source with DEPRECATED banner.
            """
        ).strip()
    )
    if dry_run:
        return

    stub = (
        DEPRECATED.format(name=source.name)
        + f'"""Tests split to {", ".join(target_name(d) for d in domains)} — see T16 fixture pass."""\n'
    )
    if stub.strip() != body.strip()[: len(stub.strip())]:
        backup = source.with_suffix(".py.bak-split")
        shutil.copy2(source, backup)
        source.write_text(stub, encoding="utf-8")
        print(f"Wrote stub to {source.name}; backup {backup.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List test_routes_* with inferred domains")
    parser.add_argument("--dry-run", action="store_true", help="Print plan only")
    parser.add_argument("--apply", action="store_true", help="Write deprecation stub after manual copy")
    parser.add_argument("--domains", type=str, default="", help="Comma-separated domain slugs")
    parser.add_argument("files", nargs="*", help="Route test files (relative to FHD/tests/routes or absolute)")
    args = parser.parse_args()

    if args.list:
        list_candidates()
        return

    if not args.files:
        parser.error("Provide file path(s) or use --list")

    for raw in args.files:
        path = Path(raw)
        if not path.is_absolute():
            path = ROUTES_DIR / path.name if path.parent == Path(".") else FHD_ROOT / path
        domains = [d.strip() for d in args.domains.split(",") if d.strip()] or infer_domains(path)
        apply_split(path, domains, dry_run=not args.apply)


if __name__ == "__main__":
    main()
