#!/usr/bin/env python3
"""Verify Tier 1/2 docs, MkDocs nav, relative links, archive banners, and Tier 3 policy."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

FHD_ROOT = Path(__file__).resolve().parents[2]
TIER1 = FHD_ROOT / "config" / "tier1_docs.json"
TIER2 = FHD_ROOT / "config" / "tier2_docs.json"
ARCHIVE = FHD_ROOT / "config" / "docs_archive.json"
TIER3_POLICY = FHD_ROOT / "config" / "tier3_docs_policy.json"
MKDOCS = FHD_ROOT / "mkdocs.yml"
XCMAX_ROOT = FHD_ROOT.parent
DOCS_ROOT = FHD_ROOT / "docs"

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def walk_mkdocs_nav(nav: object, out: list[str]) -> None:
    if isinstance(nav, str):
        if nav.endswith(".md"):
            out.append(nav)
        return
    if isinstance(nav, list):
        for item in nav:
            walk_mkdocs_nav(item, out)
        return
    if isinstance(nav, dict):
        for value in nav.values():
            walk_mkdocs_nav(value, out)


def resolve_link(source: Path, target: str) -> Path | None:
    t = target.strip()
    if not t or t.startswith(("#", "http://", "https://", "mailto:")):
        return None
    if t.startswith("/"):
        return FHD_ROOT / "docs" / t.lstrip("/")
    base = source.parent
    # strip anchor
    path_part = t.split("#", 1)[0]
    if not path_part:
        return None
    return (base / path_part).resolve()


def parse_frontmatter(text: str) -> dict[str, str] | None:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def tier_paths_from_config() -> tuple[set[Path], list[Path], list[Path]]:
    t1 = load_json(TIER1)
    t2 = load_json(TIER2) if TIER2.is_file() else {"fhd_docs": []}
    tier1_paths = [FHD_ROOT / p for p in t1.get("fhd_docs") or []]
    tier2_paths = [FHD_ROOT / p for p in t2.get("fhd_docs") or []]
    exempt = {p.resolve() for p in tier1_paths + tier2_paths}
    return exempt, tier1_paths, tier2_paths


def archive_banner_paths() -> set[Path]:
    if not ARCHIVE.is_file():
        return set()
    arch = load_json(ARCHIVE)
    marker = arch["marker"]
    targets: set[Path] = set()
    for rel in arch.get("root_archive_files") or []:
        p = FHD_ROOT / rel
        if p.is_file() and marker in p.read_text(encoding="utf-8"):
            targets.add(p.resolve())
    excludes = tuple(arch.get("exclude_suffixes") or [])
    for pattern in arch.get("globs") or []:
        for p in FHD_ROOT.glob(pattern):
            if p.is_file() and p.name not in excludes:
                if marker in p.read_text(encoding="utf-8"):
                    targets.add(p.resolve())
    return targets


def iter_tier3_candidates(exempt: set[Path]) -> list[Path]:
    out: list[Path] = []
    for p in sorted(DOCS_ROOT.rglob("*.md")):
        if p.resolve() in exempt:
            continue
        out.append(p)
    return out


def validate_tier3_frontmatter(path: Path, policy: dict) -> list[str]:
    errs: list[str] = []
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(FHD_ROOT).as_posix()
    fm = parse_frontmatter(text)
    if fm is None:
        return [f"tier3 missing frontmatter: {rel}"]

    for key in policy.get("required_frontmatter_keys") or []:
        if key not in fm:
            errs.append(f"tier3 frontmatter missing {key!r}: {rel}")

    if fm.get("tier") != "3":
        errs.append(f"tier3 frontmatter tier must be '3': {rel}")

    status = fm.get("status")
    allowed = policy.get("allowed_status") or ["active", "archived"]
    if status not in allowed:
        errs.append(f"tier3 invalid status {status!r}: {rel}")

    reviewed = fm.get("last_reviewed", "")
    if not DATE_RE.match(reviewed):
        errs.append(f"tier3 invalid last_reviewed: {rel}")
    else:
        try:
            date.fromisoformat(reviewed)
        except ValueError:
            errs.append(f"tier3 invalid last_reviewed date: {rel}")

    prefix = policy.get("archived_path_prefix") or "docs/_archive/"
    if status == "archived" and not rel.startswith(prefix):
        errs.append(f"tier3 archived must live under {prefix}: {rel}")

    return errs


def check_tier3_docs(
    errors: list[str],
    *,
    strict: bool,
    report_only: bool,
) -> int:
    if not TIER3_POLICY.is_file():
        if strict:
            errors.append("missing config/tier3_docs_policy.json")
        return 0

    policy = load_json(TIER3_POLICY)
    exempt, _, _ = tier_paths_from_config()
    implicit = archive_banner_paths() if policy.get("implicit_tier3_via_archive_banner") else set()
    candidates = iter_tier3_candidates(exempt)
    missing_fm = 0
    invalid_fm = 0

    for path in candidates:
        rel = path.relative_to(FHD_ROOT)
        if path.resolve() in implicit:
            continue
        fm_errs = validate_tier3_frontmatter(path, policy)
        if fm_errs:
            if any("missing frontmatter" in e for e in fm_errs):
                missing_fm += 1
            else:
                invalid_fm += 1
            if strict:
                errors.extend(fm_errs)

    if report_only or (not strict and (missing_fm or invalid_fm)):
        print(
            f"Tier3 report: candidates={len(candidates)} "
            f"implicit_banner={len(implicit)} missing_frontmatter={missing_fm} "
            f"invalid_frontmatter={invalid_fm} (strict={strict})"
        )
    return missing_fm + invalid_fm


def git_added_md_paths(base_ref: str) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=A", f"{base_ref}...HEAD"],
            cwd=FHD_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if out.returncode != 0:
        return []
    paths: list[Path] = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line.endswith(".md"):
            continue
        p = (FHD_ROOT / line).resolve() if not Path(line).is_absolute() else Path(line)
        if not str(p).startswith(str(DOCS_ROOT.resolve())):
            continue
        if p.is_file():
            paths.append(p)
    return paths


def check_added_md_frontmatter(base_ref: str, errors: list[str]) -> None:
    if not TIER3_POLICY.is_file():
        errors.append("missing config/tier3_docs_policy.json")
        return
    policy = load_json(TIER3_POLICY)
    exempt, _, _ = tier_paths_from_config()
    for path in git_added_md_paths(base_ref):
        if path.resolve() in exempt:
            continue
        errors.extend(validate_tier3_frontmatter(path, policy))


def check_relative_links(docs: list[Path], errors: list[str]) -> None:
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for raw in LINK_RE.findall(text):
            resolved = resolve_link(doc, raw)
            if resolved is None:
                continue
            try:
                under_docs = resolved.is_relative_to((FHD_ROOT / "docs").resolve())
            except AttributeError:
                under_docs = str(resolved).startswith(str((FHD_ROOT / "docs").resolve()))
            if under_docs and not resolved.is_file():
                rel = doc.relative_to(FHD_ROOT)
                errors.append(f"broken link in {rel}: ({raw})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify FHD documentation SSOT")
    parser.add_argument(
        "--tier3-report",
        action="store_true",
        help="Print Tier 3 frontmatter gap stats without failing",
    )
    parser.add_argument(
        "--tier3-strict",
        action="store_true",
        help="Fail if any Tier 3 doc lacks valid frontmatter",
    )
    parser.add_argument(
        "--check-added-md",
        metavar="BASE_REF",
        help="Fail on newly added docs/*.md without Tier 3 frontmatter (PR guard)",
    )
    args = parser.parse_args()

    errors: list[str] = []

    if yaml is None:
        errors.append("PyYAML required (install mkdocs-material)")

    t1 = load_json(TIER1)
    _, tier1_paths, tier2_paths = tier_paths_from_config()

    for path in tier1_paths + tier2_paths:
        if not path.is_file():
            errors.append(f"missing: {path.relative_to(FHD_ROOT)}")

    monorepo = (XCMAX_ROOT / "成都修茈科技有限公司").is_dir()
    for rel in t1.get("xcmax_sibling_docs") or []:
        if not (XCMAX_ROOT / rel).is_file():
            if monorepo:
                errors.append(f"XCMAX sibling missing: {rel}")

    if yaml and MKDOCS.is_file():
        mk = yaml.safe_load(MKDOCS.read_text(encoding="utf-8"))
        nav_paths: list[str] = []
        walk_mkdocs_nav(mk.get("nav") or [], nav_paths)
        allowed = {p.relative_to(FHD_ROOT).as_posix() for p in tier1_paths + tier2_paths}
        for nav_rel in nav_paths:
            full = FHD_ROOT / "docs" / nav_rel
            key = full.relative_to(FHD_ROOT).as_posix()
            if not full.is_file():
                errors.append(f"mkdocs nav missing file: {nav_rel}")
            elif key not in allowed:
                errors.append(f"mkdocs nav not in tier1/tier2 config: {nav_rel}")

    check_relative_links(tier1_paths, errors)

    forbidden_in_tier1 = (
        "FLASK_ENV",
        "CUSTOMERS_DB_URL",
        "USERS_DB_URL",
        "/apidocs",
        "sqlite:///app/products.db",
    )
    for path in tier1_paths:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(FHD_ROOT)
        for token in forbidden_in_tier1:
            if token in text:
                errors.append(f"tier1 outdated content ({token!r}): {rel}")

    reports_fix_link = re.compile(
        r"\]\((?:\.\./)*reports/(?!_completed/)[^)]*(?:FIX_REPORT|FIX_SUMMARY|TRACKING)",
        re.I,
    )
    for path in tier1_paths:
        if reports_fix_link.search(path.read_text(encoding="utf-8")):
            errors.append(
                f"tier1 links to archaeological report: {path.relative_to(FHD_ROOT)}"
            )

    if ARCHIVE.is_file():
        arch = load_json(ARCHIVE)
        marker = arch["marker"]
        targets: list[Path] = []
        for rel in arch.get("root_archive_files") or []:
            p = FHD_ROOT / rel
            if p.is_file():
                targets.append(p)
        excludes = tuple(arch.get("exclude_suffixes") or [])
        for pattern in arch.get("globs") or []:
            for p in FHD_ROOT.glob(pattern):
                if p.is_file() and p.name not in excludes:
                    targets.append(p)
        seen: set[Path] = set()
        for p in targets:
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            if marker not in p.read_text(encoding="utf-8"):
                errors.append(f"archive banner missing: {p.relative_to(FHD_ROOT)}")

    if args.check_added_md:
        check_added_md_frontmatter(args.check_added_md, errors)
    elif args.tier3_strict or args.tier3_report:
        check_tier3_docs(
            errors,
            strict=args.tier3_strict,
            report_only=args.tier3_report and not args.tier3_strict,
        )

    if errors:
        print("Doc verification FAILED:", file=sys.stderr)
        for line in errors:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print(
        f"OK: tier1={len(tier1_paths)} tier2={len(tier2_paths)} "
        f"sibling={len(t1.get('xcmax_sibling_docs') or [])} links+banners+nav"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
