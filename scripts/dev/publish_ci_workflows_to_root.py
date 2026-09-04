#!/usr/bin/env python3
"""Publish FHD / MODstore GitHub Actions to XCMAX root .github/workflows/ (CI SSOT).

用法：
  python scripts/dev/publish_ci_workflows_to_root.py            # 默认 --apply，写入根仓
  python scripts/dev/publish_ci_workflows_to_root.py --check    # 仅校验，不写入
  python scripts/dev/publish_ci_workflows_to_root.py --apply    # 显式写入

退出码：--check 模式下，存在漂移或新增返回 1；--apply 模式始终 0。
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FHD_WF = ROOT / "FHD" / ".github" / "workflows"
MOD_WF = ROOT / "成都修茈科技有限公司" / "MODstore_deploy" / ".github" / "workflows"
CORP_WF = ROOT / "成都修茈科技有限公司" / ".github" / "workflows"
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

DEFAULTS_CORP = """
defaults:
  run:
    working-directory: 成都修茈科技有限公司
""".strip()

WORKFLOW_RENAMES = {
    "ci-cd.yml": "fhd-ci-cd.yml",
    "release-gate-ci.yml": "fhd-release-gate-ci.yml",
    "ci-mobile-flutter.yml": "fhd-ci-mobile-flutter.yml",
    "release-desktop.yml": "fhd-release-desktop.yml",
    "release-web.yml": "fhd-release-web.yml",
    "release-android.yml": "fhd-release-android.yml",
    "release-orchestrator.yml": "fhd-release-orchestrator.yml",
    "performance-smoke.yml": "fhd-performance-smoke.yml",
    "neuro_migration_check.yml": "fhd-neuro-migration-check.yml",
    "modstore-tests.yml": "fhd-modstore-tests.yml",
    "intent-benchmark.yml": "fhd-intent-benchmark.yml",
    "slo-metrics-collect.yml": "fhd-slo-metrics-collect.yml",
}

# These workflows use only absolute/remote commands.  Injecting the normal FHD
# working directory before checkout makes their first preflight step fail.
FHD_NO_DEFAULTS = {
    "cvm-autonomy-watcher.yml",
    # This release scan intentionally covers the monorepo and already uses
    # explicit FHD/ paths where component-local access is required.
    "security-full-scan.yml",
}
MOD_NO_DEFAULTS = {"prod-deploy-receipt.yml", "prod-deploy.yml"}

MOD_RENAMES = {
    "ci-backend-python.yml": "modstore-ci-backend-python.yml",
    "market-e2e.yml": "modstore-market-e2e.yml",
    "prod-deploy.yml": "modstore-prod-deploy.yml",
}

# These source workflows live below the monorepo root, where GitHub would
# otherwise ignore them. Publish component gates without a root counterpart.
CORP_RENAMES = {
    "ci-root-frontend.yml": "corp-root-frontend.yml",
    "ci-vibe-coding.yml": "corp-vibe-coding.yml",
    "ci-marketing-site.yml": "corp-marketing-site.yml",
    "ci-payment-java.yml": "corp-payment-java.yml",
    "ci-runtime-artifacts-guard.yml": "corp-runtime-artifacts-guard.yml",
}


def _insert_defaults(content: str, defaults: str) -> str:
    if "defaults:\n  run:\n    working-directory:" in content:
        return content
    m = re.search(r"\njobs:\n", content)
    if not m:
        raise ValueError("no jobs: anchor")
    return content[: m.start()] + "\n\n" + defaults + "\n" + content[m.start() :]


def _prefix_fhd_paths(content: str, out_name: str) -> str:
    source_workflow = out_name.removeprefix("fhd-")
    content = content.replace(
        f".github/workflows/{source_workflow}",
        f".github/workflows/{out_name}",
    )
    for wf in (
        "release-desktop.yml",
        "release-web.yml",
        "release-android.yml",
    ):
        content = content.replace(
            f'gh workflow run "{wf}"',
            f'gh workflow run "fhd-{wf}"',
        )
        # Defensive: unquoted matrix list entries (e.g. `- release-desktop.yml`)
        # must reference the published root name. Idempotent — a `- fhd-...`
        # entry is not preceded by `- ` + the bare name, so it won't re-match.
        content = re.sub(
            rf"(\n[ \t]+-[ \t]+){re.escape(wf)}(?=[ \t]*(?:\n|$))",
            rf"\1fhd-{wf}",
            content,
        )

    def repl_path(m: re.Match[str]) -> str:
        indent = m.group(1)
        raw = m.group(2)
        # Quoted list items are not always paths. Keep workflow-dispatch version
        # choices intact instead of rewriting `1.0.0.0` as `FHD/1.0.0.0`.
        if re.fullmatch(r"\d+(?:\.\d+){2,3}", raw):
            return f'{indent}- "{raw}"'
        if raw.startswith(("FHD/", ".github/", "scripts/", "_archive/")):
            return f'{indent}- "{raw}"'
        if raw.startswith("成都"):
            return f'{indent}- "{raw}"'
        return f'{indent}- "FHD/{raw}"'

    # Only rewrite YAML list items. A broad ``- "..."`` pattern also matches
    # shell syntax such as ``bash -s -- "$arg"`` inside run blocks.
    content = re.sub(r'(?m)^([ \t]*)-\s+"([^"]+)"', repl_path, content)

    # NOTE: the guard-temp-scripts allow-list/patterns now compute `rel="${file#FHD/}"`
    # directly in the FHD source (ci-cd.yml), so the previous publish-time string
    # rewrites for that block are no longer needed.

    content = content.replace(
        "cache-dependency-path: frontend/package-lock.json",
        "cache-dependency-path: FHD/frontend/package-lock.json",
    )
    content = re.sub(
        r"(?<!FHD/)desktop/package-lock\.json",
        "FHD/desktop/package-lock.json",
        content,
    )
    content = content.replace(
        "working-directory: frontend",
        "working-directory: FHD/frontend",
    )
    content = content.replace(
        "working-directory: mobile-flutter-poc",
        "working-directory: FHD/mobile-flutter-poc",
    )
    if out_name == "fhd-langgraph-packages.yml":
        content = content.replace(
            'path: "packages/xcagi_langgraph_',
            'path: "FHD/packages/xcagi_langgraph_',
        )
    content = content.replace(
        "path: mobile-flutter-poc/build/",
        "path: FHD/mobile-flutter-poc/build/",
    )
    # desktop-build-smoke job runs from repo root (no workflow-level defaults),
    # so working-directory: desktop must be rewritten to FHD/desktop.
    # Use \n anchor to avoid clobbering "working-directory: desktop-shell".
    content = content.replace(
        "working-directory: desktop\n",
        "working-directory: FHD/desktop\n",
    )
    # upload-artifact / download-artifact / build-push-action ignore defaults.run.working-directory
    content = re.sub(r"(?m)^([ \t]+)(dist/deploy/)", r"\1FHD/\2", content)
    content = content.replace("path: dist/deploy\n", "path: FHD/dist/deploy\n")
    content = content.replace("output: metrics/", "output: FHD/metrics/")
    content = content.replace(
        "path: build/ci-sunbird-artifact/**",
        "path: FHD/build/ci-sunbird-artifact/**",
    )
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
    mod_root = "成都修茈科技有限公司/MODstore_deploy"

    def repl_path(m: re.Match[str]) -> str:
        indent = m.group(1)
        raw = m.group(2)
        if raw.startswith(("成都", ".github/", "scripts/")):
            return f'{indent}- "{raw}"'
        if raw.startswith("FHD/"):
            return f'{indent}- "{raw}"'
        return f'{indent}- "{mod_root}/{raw}"'

    content = re.sub(r'(?m)^([ \t]*)-\s+"([^"]+)"', repl_path, content)
    content = content.replace(
        ".github/workflows/ci-backend-python.yml",
        f".github/workflows/{out_name}",
    )
    # GitHub resolves action inputs and job-level working directories from the
    # repository root, not from workflow-level defaults.run.working-directory.
    content = content.replace(
        "working-directory: market",
        f"working-directory: {mod_root}/market",
    )
    content = content.replace(
        "cache-dependency-path: market/package-lock.json",
        f"cache-dependency-path: {mod_root}/market/package-lock.json",
    )
    content = content.replace(
        "working-directory: java_payment_service",
        f"working-directory: {mod_root}/java_payment_service",
    )
    content = content.replace(
        "cache-dependency-path: java_payment_service/pom.xml",
        f"cache-dependency-path: {mod_root}/java_payment_service/pom.xml",
    )
    content = content.replace(
        "path: market/playwright-report/",
        f"path: {mod_root}/market/playwright-report/",
    )
    content = content.replace(
        ".github/workflows/market-e2e.yml",
        f".github/workflows/{out_name}",
    )
    content = content.replace(
        "working-directory: market",
        "working-directory: 成都修茈科技有限公司/MODstore_deploy/market",
    )
    content = content.replace(
        "cache-dependency-path: market/package-lock.json",
        "cache-dependency-path: 成都修茈科技有限公司/MODstore_deploy/market/package-lock.json",
    )
    content = content.replace(
        "path: market/playwright-report/",
        "path: 成都修茈科技有限公司/MODstore_deploy/market/playwright-report/",
    )
    content = content.replace(
        "working-directory: desktop-shell",
        f"working-directory: {mod_root}/desktop-shell",
    )
    return content


def _render_fhd(src: Path) -> tuple[str, str] | None:
    """渲染 FHD 源文件的根仓副本内容，返回 (out_name, full_content) 或 None（跳过）。"""
    body = src.read_text(encoding="utf-8").strip()
    if not body or "jobs:" not in body:
        return None
    body = re.sub(
        r"^# CI SSOT: edit this file, then run: python scripts/dev/publish_ci_workflows_to_root\.py\n",
        "",
        body,
    )
    out_name = WORKFLOW_RENAMES.get(src.name, f"fhd-{src.name}")
    if src.name not in FHD_NO_DEFAULTS:
        body = _insert_defaults(body, DEFAULTS_FHD)
    body = _prefix_fhd_paths(body, out_name)
    header = (
        f"# CI SSOT: generated from FHD/.github/workflows/{src.name} — DO NOT edit here.\n"
        f"# Edit that source, then run: python scripts/dev/publish_ci_workflows_to_root.py\n"
    )
    return out_name, header + body + "\n"


def _render_mod(src: Path) -> tuple[str, str] | None:
    """渲染 MODstore 源文件的根仓副本内容。"""
    body = src.read_text(encoding="utf-8").strip()
    if not body or "jobs:" not in body:
        return None
    out_name = MOD_RENAMES.get(src.name, f"modstore-{src.name}")
    if src.name not in MOD_NO_DEFAULTS:
        body = _insert_defaults(body, DEFAULTS_MOD)
    body = _prefix_mod_paths(body, out_name)
    header = (
        f"# CI SSOT: generated from MODstore_deploy/.github/workflows/{src.name} "
        "— DO NOT edit here.\n"
        "# Edit that source, then run: python scripts/dev/publish_ci_workflows_to_root.py\n"
    )
    return out_name, header + body + "\n"


def _prefix_trigger_paths(content: str, out_name: str) -> str:
    """Prefix only ``on.*.paths`` entries for a nested workflow."""
    result: list[str] = []
    paths_indent: int | None = None
    item_re = re.compile(r"^(\s*)-\s+(['\"])([^'\"]+)\2\s*$")
    for line in content.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped == "paths:":
            paths_indent = indent
        elif paths_indent is not None and stripped and indent <= paths_indent:
            paths_indent = None
        if paths_indent is not None and indent > paths_indent:
            match = item_re.match(line)
            if match:
                raw = match.group(3)
                if raw.startswith(".github/workflows/"):
                    raw = f".github/workflows/{out_name}"
                elif not raw.startswith("成都修茈科技有限公司/"):
                    raw = f"成都修茈科技有限公司/{raw}"
                line = f"{match.group(1)}- {match.group(2)}{raw}{match.group(2)}"
        result.append(line)
    return "\n".join(result)


def _render_corp(src: Path) -> tuple[str, str] | None:
    """Render selected corporate component CI workflows at repository root."""
    out_name = CORP_RENAMES.get(src.name)
    if out_name is None:
        return None
    body = src.read_text(encoding="utf-8").strip()
    if not body or "jobs:" not in body:
        return None
    body = _prefix_trigger_paths(body, out_name)
    if src.name in {"ci-root-frontend.yml", "ci-marketing-site.yml"}:
        body = _insert_defaults(body, DEFAULTS_CORP)
    body = body.replace(
        "working-directory: vibe-coding",
        "working-directory: 成都修茈科技有限公司/vibe-coding",
    )
    body = body.replace(
        "working-directory: MODstore_deploy/java_payment_service",
        "working-directory: 成都修茈科技有限公司/MODstore_deploy/java_payment_service",
    )
    if src.name == "ci-root-frontend.yml":
        body = body.replace(
            "cache-dependency-path: package-lock.json",
            "cache-dependency-path: 成都修茈科技有限公司/package-lock.json",
        )
        body = body.replace(
            "hashFiles('package-lock.json')",
            "hashFiles('成都修茈科技有限公司/package-lock.json')",
        )
        body = body.replace("path: coverage/", "path: 成都修茈科技有限公司/coverage/")
        body = body.replace(
            "path: playwright-report/",
            "path: 成都修茈科技有限公司/playwright-report/",
        )
    if src.name == "ci-runtime-artifacts-guard.yml":
        body = body.replace(
            "'MODstore_deploy/",
            "'成都修茈科技有限公司/MODstore_deploy/",
        )
    header = (
        f"# CI SSOT: generated from 成都修茈科技有限公司/.github/workflows/{src.name} "
        "— DO NOT edit here.\n"
        "# Edit that source, then run: python scripts/dev/publish_ci_workflows_to_root.py\n"
    )
    return out_name, header + body + "\n"


def _diff_one(out_name: str, expected: str) -> str:
    """对比根仓现有副本与期望内容，返回 diff 字符串（无差异返回空串）。"""
    dst = OUT / out_name
    if not dst.exists():
        return f"  + {out_name} (NEW)"
    actual = dst.read_text(encoding="utf-8")
    if actual == expected:
        return ""
    diff = difflib.unified_diff(
        actual.splitlines(keepends=True),
        expected.splitlines(keepends=True),
        fromfile=f"a/.github/workflows/{out_name}",
        tofile=f"b/.github/workflows/{out_name}",
        n=1,
    )
    return "  ~ " + out_name + "\n" + "".join("    " + line for line in diff)


def publish_fhd(apply: bool = True) -> tuple[list[str], list[str]]:
    """返回 (written, drifts)。apply=True 时写入，否则仅对比。"""
    written: list[str] = []
    drifts: list[str] = []
    for src in sorted(FHD_WF.glob("*.yml")):
        rendered = _render_fhd(src)
        if rendered is None:
            continue
        out_name, content = rendered
        diff = _diff_one(out_name, content)
        if diff:
            drifts.append(diff)
            if apply:
                (OUT / out_name).write_text(content, encoding="utf-8")
                written.append(out_name)
        else:
            written.append(out_name)
    return written, drifts


def publish_mod(apply: bool = True) -> tuple[list[str], list[str]]:
    written: list[str] = []
    drifts: list[str] = []
    for src in sorted(MOD_WF.glob("*.yml")):
        rendered = _render_mod(src)
        if rendered is None:
            continue
        out_name, content = rendered
        diff = _diff_one(out_name, content)
        if diff:
            drifts.append(diff)
            if apply:
                (OUT / out_name).write_text(content, encoding="utf-8")
                written.append(out_name)
        else:
            written.append(out_name)
    return written, drifts


def publish_corp(apply: bool = True) -> tuple[list[str], list[str]]:
    written: list[str] = []
    drifts: list[str] = []
    for src_name in sorted(CORP_RENAMES):
        rendered = _render_corp(CORP_WF / src_name)
        if rendered is None:
            continue
        out_name, content = rendered
        diff = _diff_one(out_name, content)
        if diff:
            drifts.append(diff)
            if apply:
                (OUT / out_name).write_text(content, encoding="utf-8")
                written.append(out_name)
        else:
            written.append(out_name)
    return written, drifts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="仅校验，不写入（CI 用）")
    mode.add_argument("--apply", action="store_true", help="写入根仓副本（默认）")
    args = parser.parse_args()

    apply_mode = not args.check  # 默认 apply
    print(f"模式: {'--apply (写入)' if apply_mode else '--check (仅校验)'}")
    print()

    fhd_written, fhd_drifts = publish_fhd(apply=apply_mode)
    mod_written, mod_drifts = publish_mod(apply=apply_mode)
    corp_written, corp_drifts = publish_corp(apply=apply_mode)

    print(f"FHD ({len(fhd_written)} 文件):", ", ".join(fhd_written))
    print(f"MODstore ({len(mod_written)} 文件):", ", ".join(mod_written))
    print(f"Corporate ({len(corp_written)} 文件):", ", ".join(corp_written))
    print()

    all_drifts = fhd_drifts + mod_drifts + corp_drifts
    if all_drifts:
        if apply_mode:
            print(f"已写入 {len(all_drifts)} 个漂移文件。下一步：")
            print("  git add .github/workflows/")
            print('  git commit -m "ci: sync workflows from FHD/MODstore sources"')
        else:
            print(f"发现 {len(all_drifts)} 处漂移：")
            for d in all_drifts:
                print(d)
            print()
            print("修复：python scripts/dev/publish_ci_workflows_to_root.py --apply")
            return 1
    else:
        print("无漂移，所有副本与源一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
