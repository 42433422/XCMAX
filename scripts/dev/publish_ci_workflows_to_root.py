#!/usr/bin/env python3
"""Publish FHD / MODstore GitHub Actions to XCMAX root .github/workflows/ (CI SSOT)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FHD_WF = ROOT / "FHD" / ".github" / "workflows"
MOD_WF = ROOT / "成都修茈科技有限公司" / "MODstore_deploy" / ".github" / "workflows"
OUT = ROOT / ".github" / "workflows"

DEFAULTS_FHD = """
defaults:
  run:
    working-directory: FHD
""".strip()

DEFAULTS_MOD = """
defaults:
  run:
    working-directory: 成都修茈科技有限公司/MODstore_deploy
""".strip()

WORKFLOW_RENAMES = {
    "deploy.yml": "fhd-deploy.yml",
    "ci-cd.yml": "fhd-ci-cd.yml",
    "release-gate-ci.yml": "fhd-release-gate-ci.yml",
    "ci-mobile-android.yml": "fhd-ci-mobile-android.yml",
    "release-desktop.yml": "fhd-release-desktop.yml",
    "release-web.yml": "fhd-release-web.yml",
    "release-android.yml": "fhd-release-android.yml",
    "performance-smoke.yml": "fhd-performance-smoke.yml",
    "neuro_migration_check.yml": "fhd-neuro-migration-check.yml",
    "modstore-tests.yml": "fhd-modstore-tests.yml",
    "intent-benchmark.yml": "fhd-intent-benchmark.yml",
    "slo-metrics-collect.yml": "fhd-slo-metrics-collect.yml",
    "deploy.yml": "fhd-deploy.yml",
}

MOD_RENAMES = {
    "ci-backend-python.yml": "modstore-ci-backend-python.yml",
    "build-desktop.yml": "modstore-build-desktop.yml",
    "market-e2e.yml": "modstore-market-e2e.yml",
}


def _insert_defaults(content: str, defaults: str) -> str:
    if "defaults:\n  run:\n    working-directory:" in content:
        return content
    m = re.search(r"\njobs:\n", content)
    if not m:
        raise ValueError("no jobs: anchor")
    return content[: m.start()] + "\n\n" + defaults + "\n" + content[m.start() :]


def _prefix_fhd_paths(content: str, out_name: str) -> str:
    content = content.replace(
        "gh workflow run deploy.yml",
        "gh workflow run fhd-deploy.yml",
    )
    content = content.replace(
        ".github/workflows/ci-mobile-android.yml",
        f".github/workflows/{out_name}",
    )

    def repl_path(m: re.Match[str]) -> str:
        raw = m.group(1)
        if raw.startswith(("FHD/", ".github/", "scripts/", "_archive/")):
            return f'- "{raw}"'
        if raw.startswith("成都"):
            return f'- "{raw}"'
        return f'- "FHD/{raw}"'

    content = re.sub(r'-\s+"([^"]+)"', repl_path, content)

    guard_old = """            if [[ "${file}" == XCAGI/tools/* ]] || [[ "${file}" == XCAGI/archive/* ]] || \\
               [[ "${file}" == tools/* ]] || [[ "${file}" == archive/* ]]; then"""
    guard_new = """            rel="${file#FHD/}"
            if [[ "${rel}" == XCAGI/tools/* ]] || [[ "${rel}" == XCAGI/archive/* ]] || \\
               [[ "${rel}" == tools/* ]] || [[ "${rel}" == archive/* ]]; then"""
    content = content.replace(guard_old, guard_new)

    guard_old2 = """            if [[ "${file}" =~ (^|/)产品文件夹/(fix_|check_|final_).+\\.py$ ]] || \\
               [[ "${file}" =~ ^(fix_|check_|final_).+\\.py$ ]]; then"""
    guard_new2 = """            if [[ "${rel}" =~ (^|/)产品文件夹/(fix_|check_|final_).+\\.py$ ]] || \\
               [[ "${rel}" =~ ^(fix_|check_|final_).+\\.py$ ]]; then"""
    content = content.replace(guard_old2, guard_new2)

    content = content.replace(
        "cache-dependency-path: frontend/package-lock.json",
        "cache-dependency-path: FHD/frontend/package-lock.json",
    )
    content = content.replace(
        "working-directory: frontend",
        "working-directory: FHD/frontend",
    )
    # upload-artifact / download-artifact / build-push-action ignore defaults.run.working-directory
    content = content.replace("dist/deploy/", "FHD/dist/deploy/")
    content = content.replace("path: dist/deploy\n", "path: FHD/dist/deploy\n")
    content = content.replace(
        "          context: .\n          file: ./docker/Dockerfile.fhd-api",
        "          context: FHD\n          file: FHD/docker/Dockerfile.fhd-api",
    )
    content = content.replace(
        "          context: .\n          file: ./Dockerfile",
        "          context: FHD\n          file: FHD/Dockerfile",
    )

    return content


def _prefix_mod_paths(content: str, out_name: str) -> str:
    def repl_path(m: re.Match[str]) -> str:
        raw = m.group(1)
        if raw.startswith(("成都", ".github/", "scripts/")):
            return f'- "{raw}"'
        if raw.startswith("FHD/"):
            return f'- "{raw}"'
        return f'- "成都修茈科技有限公司/MODstore_deploy/{raw}"'

    content = re.sub(r'-\s+"([^"]+)"', repl_path, content)
    content = content.replace(
        ".github/workflows/ci-backend-python.yml",
        f".github/workflows/{out_name}",
    )
    return content


def publish_fhd() -> list[str]:
    written: list[str] = []
    for src in sorted(FHD_WF.glob("*.yml")):
        body = src.read_text(encoding="utf-8").strip()
        if not body or "jobs:" not in body:
            continue
        out_name = WORKFLOW_RENAMES.get(src.name, f"fhd-{src.name}")
        body = _insert_defaults(body, DEFAULTS_FHD)
        body = _prefix_fhd_paths(body, out_name)
        header = f"# CI SSOT: generated from FHD/.github/workflows/{src.name} — edit root copy only.\n"
        (OUT / out_name).write_text(header + body, encoding="utf-8")
        written.append(out_name)
    return written


def publish_mod() -> list[str]:
    written: list[str] = []
    for src in sorted(MOD_WF.glob("*.yml")):
        body = src.read_text(encoding="utf-8").strip()
        if not body or "jobs:" not in body:
            continue
        out_name = MOD_RENAMES.get(src.name, f"modstore-{src.name}")
        body = _insert_defaults(body, DEFAULTS_MOD)
        body = _prefix_mod_paths(body, out_name)
        header = (
            f"# CI SSOT: generated from MODstore_deploy/.github/workflows/{src.name} "
            "— edit root copy only.\n"
        )
        (OUT / out_name).write_text(header + body, encoding="utf-8")
        written.append(out_name)
    return written


def main() -> None:
    fhd = publish_fhd()
    mod = publish_mod()
    print("FHD:", ", ".join(fhd))
    print("MODstore:", ", ".join(mod))


if __name__ == "__main__":
    main()
