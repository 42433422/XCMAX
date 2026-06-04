#!/usr/bin/env python3
"""Move test_coverage_ramp_phase* into tests/unit|tests/routes with domain-oriented names.

Does not merge test bodies; renames and relocates per MIGRATION_RAMP batches.
Idempotent: skips if destination already exists.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

TESTS = Path(__file__).resolve().parents[2] / "tests"
DEPRECATED = "# DEPRECATED (migrated): was {name}\n"

BATCHES: dict[int, tuple[str, ...]] = {
    1: (
        "test_coverage_ramp_phase14_ai_chat.py",
        "test_coverage_ramp_phase14_mod_wechat.py",
        "test_coverage_ramp_phase54_routes.py",
        "test_coverage_ramp_phase54_backend.py",
    ),
    2: (
        "test_coverage_ramp_phase12_application.py",
        "test_coverage_ramp_phase12_quick_wins.py",
        "test_coverage_ramp_phase6_workflow.py",
        "test_coverage_ramp_phase6_services.py",
    ),
    3: (
        "test_coverage_ramp_phase4_workflow.py",
        "test_coverage_ramp_phase10_routes.py",
        "test_coverage_ramp_phase10_backend.py",
        "test_coverage_ramp_phase13_routes.py",
        "test_coverage_ramp_phase13_backend.py",
        "test_coverage_ramp_phase17_routes.py",
        "test_coverage_ramp_phase20_routes.py",
        "test_coverage_ramp_phase51_routes.py",
        "test_coverage_ramp_phase51_backend.py",
    ),
    4: (
        "test_coverage_ramp_phase19_neuro.py",
        "test_coverage_ramp_phase19_quick_wins.py",
        "test_coverage_ramp_phase19_documents.py",
    ),
}


def _target_dir(filename: str, batch: int) -> Path:
    if batch == 1:
        if "ai_chat" in filename or "application" in filename:
            return TESTS / "unit" / "application"
        if "wechat" in filename or "backend" in filename:
            return TESTS / "unit" / "services"
    if batch == 2:
        return TESTS / "unit" / "application"
    if batch == 3 or filename.endswith("_routes.py"):
        return TESTS / "routes"
    if batch == 4 or "neuro" in filename:
        return TESTS / "neuro"
    if filename.endswith("_routes.py"):
        return TESTS / "routes"
    if filename.endswith("_backend.py") or filename.endswith("_services.py"):
        return TESTS / "unit" / "services"
    if "application" in filename:
        return TESTS / "unit" / "application"
    return TESTS / "unit" / "coverage"


def _new_name(filename: str) -> str:
    m = re.match(r"test_coverage_ramp_(.+)\.py$", filename)
    if not m:
        return filename
    slug = m.group(1)
    slug = re.sub(r"^phase\d+_?", "", slug)
    slug = re.sub(r"^phase\d+$", "ramp", slug)
    slug = slug.replace("-", "_")
    if not slug:
        slug = "ramp"
    return f"test_{slug}.py"


def _domain_hint(path: Path) -> str:
    try:
        head = path.read_text(encoding="utf-8")[:400]
    except OSError:
        return ""
    m = re.search(r"Phase\s+\d+:\s*([^\n.]+)", head)
    if m:
        hint = re.sub(r"[^a-zA-Z0-9_]+", "_", m.group(1).strip().lower())
        hint = re.sub(r"_+", "_", hint).strip("_")[:48]
        return hint
    return ""


def migrate_file(src: Path, batch: int, dry_run: bool = False) -> str | None:
    if not src.is_file():
        return None
    dest_dir = _target_dir(src.name, batch)
    base = _new_name(src.name)
    hint = _domain_hint(src)
    if hint and hint not in base:
        stem = base[:-3]
        dest_name = f"{stem}_{hint}.py"
    else:
        dest_name = base
    dest = dest_dir / dest_name
    if dest.exists() and dest.resolve() != src.resolve():
        n = 2
        while dest.exists():
            dest = dest_dir / f"{dest.stem}_v{n}.py"
            n += 1
    if dry_run:
        return f"{src.name} -> {dest.relative_to(TESTS)}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8")
    if not text.startswith("# DEPRECATED"):
        text = DEPRECATED.format(name=src.name) + text
    if dest.resolve() == src.resolve():
        dest.write_text(text, encoding="utf-8")
        return str(dest.relative_to(TESTS))
    shutil.move(str(src), str(dest))
    dest.write_text(text, encoding="utf-8")
    return str(dest.relative_to(TESTS))


def migrate_batch(batch: int, dry_run: bool = False) -> list[str]:
    files = list(BATCHES.get(batch, ()))
    if batch == 5:
        known = {f for fs in BATCHES.values() for f in fs}
        files = sorted(
            p.name
            for p in TESTS.glob("test_coverage_ramp*.py")
            if p.name not in known and "phase" not in p.name
        )
    out: list[str] = []
    for name in files:
        moved = migrate_file(TESTS / name, batch, dry_run=dry_run)
        if moved:
            out.append(moved)
    return out


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--batch", type=int, choices=[1, 2, 3, 4, 5], required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    for line in migrate_batch(args.batch, dry_run=args.dry_run):
        print(line)


if __name__ == "__main__":
    main()
