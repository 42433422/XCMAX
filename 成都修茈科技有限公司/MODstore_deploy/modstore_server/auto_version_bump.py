"""自动版本演进：bump 版本号 + 生成 CHANGELOG + 同步所有锚点。

步骤9（版本自动演进）核心补齐：
- 从 git log / PR 标签自动判断版本号 bump 类型（major/minor/patch）
- 一次性同步 VERSION.md 中定义的所有锚点文件
- 从 conventional commits 自动生成 CHANGELOG 条目
- 通过 CR 管线提交变更
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

VERSION_ANCHORS = [
    {
        "key": "pyproject_root",
        "path": "pyproject.toml",
        "pattern": r'version\s*=\s*"([\d.]+)"',
        "replacement": 'version = "{version}"',
    },
    {
        "key": "pyproject_xcagi",
        "path": "XCAGI/pyproject.toml",
        "pattern": r'version\s*=\s*"([\d.]+)"',
        "replacement": 'version = "{version}"',
    },
    {
        "key": "frontend_package",
        "path": "frontend/package.json",
        "pattern": r'"version"\s*:\s*"([\d.]+)"',
        "replacement": '"version": "{version}"',
    },
    {
        "key": "desktop_package",
        "path": "desktop/package.json",
        "pattern": r'"version"\s*:\s*"([\d.]+)"',
        "replacement": '"version": "{version}"',
    },
    {
        "key": "root_package",
        "path": "package.json",
        "pattern": r'"version"\s*:\s*"([\d.]+)"',
        "replacement": '"version": "{version}"',
    },
    {
        "key": "fastapi_app",
        "path": "app/fastapi_app.py",
        "pattern": r'version\s*=\s*"([\d.]+)"',
        "replacement": 'version="{version}"',
    },
    {
        "key": "mod_manifest",
        "path": "app/infrastructure/mods/manifest.py",
        "pattern": r'BASE_VERSION\s*=\s*"([\d.]+)"',
        "replacement": 'BASE_VERSION = "{version}"',
    },
]


def _auto_version_enabled() -> bool:
    return os.environ.get("XCAGI_AUTO_VERSION_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def get_current_version(project_root: str) -> str:
    pyproject = os.path.join(project_root, "pyproject.toml")
    if os.path.isfile(pyproject):
        with open(pyproject, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r'version\s*=\s*"([\d.]+)"', line)
                if m:
                    return m.group(1)
    return "0.0.0"


def bump_version(current: str, bump_type: str) -> str:
    parts = current.split(".")
    while len(parts) < 3:
        parts.append("0")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


def determine_bump_type(project_root: str) -> str:
    """从最近的 git commits 判断 bump 类型。"""
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", "-20"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return "patch"

        messages = proc.stdout.strip().splitlines()

        for msg in messages:
            lower = msg.lower()
            if any(kw in lower for kw in ["breaking", "break!", "major"]):
                return "major"
            if lower.startswith("feat") or lower.startswith("feature"):
                return "minor"

        return "patch"
    except Exception:
        return "patch"


def sync_version_anchors(project_root: str, new_version: str) -> List[Dict[str, Any]]:
    """同步所有版本锚点文件。"""
    results = []
    for anchor in VERSION_ANCHORS:
        full_path = os.path.join(project_root, anchor["path"])
        if not os.path.isfile(full_path):
            results.append(
                {
                    "key": anchor["key"],
                    "path": anchor["path"],
                    "status": "skipped",
                    "reason": "file not found",
                }
            )
            continue

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()

            old_version_match = re.search(anchor["pattern"], content)
            if not old_version_match:
                results.append(
                    {
                        "key": anchor["key"],
                        "path": anchor["path"],
                        "status": "skipped",
                        "reason": "version pattern not found",
                    }
                )
                continue

            old_version = old_version_match.group(1)
            if old_version == new_version:
                results.append(
                    {
                        "key": anchor["key"],
                        "path": anchor["path"],
                        "status": "already_synced",
                        "old": old_version,
                    }
                )
                continue

            replacement = anchor["replacement"].format(version=new_version)
            new_content = re.sub(anchor["pattern"], replacement, content, count=1)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            results.append(
                {
                    "key": anchor["key"],
                    "path": anchor["path"],
                    "status": "updated",
                    "old": old_version,
                    "new": new_version,
                }
            )
        except Exception as exc:
            results.append(
                {"key": anchor["key"], "path": anchor["path"], "status": "error", "error": str(exc)}
            )

    return results


def generate_changelog_entry(project_root: str, new_version: str) -> str:
    """从 git log 生成 CHANGELOG 条目。"""
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", "-50"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return ""

        messages = proc.stdout.strip().splitlines()
    except Exception:
        return ""

    features = []
    fixes = []
    chores = []
    others = []

    for msg in messages:
        lower = msg.lower()
        clean = msg.split(":", 1)[-1].strip() if ":" in msg else msg.strip()
        if lower.startswith("feat"):
            features.append(clean)
        elif lower.startswith("fix"):
            fixes.append(clean)
        elif any(lower.startswith(p) for p in ["chore", "ci", "build", "test"]):
            chores.append(clean)
        else:
            others.append(clean)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"## v{new_version} ({today})", ""]

    if features:
        lines.append("### Features")
        for f in features[:20]:
            lines.append(f"- {f}")
        lines.append("")

    if fixes:
        lines.append("### Bug Fixes")
        for f in fixes[:20]:
            lines.append(f"- {f}")
        lines.append("")

    if chores:
        lines.append("### Maintenance")
        for c in chores[:10]:
            lines.append(f"- {c}")
        lines.append("")

    return "\n".join(lines)


def prepend_changelog(project_root: str, entry: str) -> bool:
    """将新条目插入 CHANGELOG.md 的 Unreleased 区域下方。"""
    changelog_path = os.path.join(project_root, "CHANGELOG.md")
    if not os.path.isfile(changelog_path):
        return False

    with open(changelog_path, "r", encoding="utf-8") as f:
        content = f.read()

    unreleased_marker = "## Unreleased"
    if unreleased_marker in content:
        parts = content.split(unrecovered_marker, 1)
        new_content = parts[0] + unreleased_marker + "\n\n" + entry + parts[1]
    else:
        first_h2 = content.find("\n## ")
        if first_h2 > 0:
            new_content = content[:first_h2] + "\n" + entry + "\n---\n" + content[first_h2:]
        else:
            new_content = content + "\n" + entry

    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    return True


def auto_version_bump(project_root: str) -> Dict[str, Any]:
    """自动版本演进主入口：判断 bump 类型 → 同步锚点 → 生成 CHANGELOG → CR 提交。"""
    if not _auto_version_enabled():
        return {"ok": True, "skipped": True, "reason": "auto version disabled"}

    current = get_current_version(project_root)
    bump_type = determine_bump_type(project_root)
    new_version = bump_version(current, bump_type)

    logger.info("auto_version_bump: %s → %s (bump_type=%s)", current, new_version, bump_type)

    sync_results = sync_version_anchors(project_root, new_version)
    updated_count = sum(1 for r in sync_results if r.get("status") == "updated")

    changelog_entry = generate_changelog_entry(project_root, new_version)
    changelog_ok = False
    if changelog_entry:
        changelog_ok = prepend_changelog(project_root, changelog_entry)

    version_md_path = os.path.join(project_root, "VERSION.md")
    if os.path.isfile(version_md_path):
        try:
            with open(version_md_path, "r", encoding="utf-8") as f:
                vm_content = f.read()
            vm_content = vm_content.replace(current, new_version)
            with open(version_md_path, "w", encoding="utf-8") as f:
                f.write(vm_content)
        except Exception:
            logger.warning("failed to update VERSION.md")

    release_version_path = os.path.join(project_root, "release", "VERSION")
    try:
        os.makedirs(os.path.dirname(release_version_path), exist_ok=True)
        with open(release_version_path, "w", encoding="utf-8") as f:
            f.write(new_version)
    except Exception:
        logger.warning("failed to write release/VERSION")

    try:
        from modstore_server.employee_change_request_service import defer_write_as_change_request
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = str(repo_root())
        changed_files = [r["path"] for r in sync_results if r.get("status") == "updated"]
        if changelog_ok:
            changed_files.append("CHANGELOG.md")
        changed_files.append("VERSION.md")
        changed_files.append("release/VERSION")

        for rel_path in changed_files:
            full_path = os.path.join(project_root, rel_path)
            if os.path.isfile(full_path):
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
                try:
                    defer_write_as_change_request(
                        source_employee_id="deploy-release-officer",
                        workspace_root=root,
                        path=rel_path,
                        content=content,
                    )
                except Exception:
                    logger.warning("CR for %s failed", rel_path)
    except Exception:
        logger.warning("CR pipeline not available, version files written directly")

    return {
        "ok": True,
        "old_version": current,
        "new_version": new_version,
        "bump_type": bump_type,
        "anchors_synced": updated_count,
        "changelog_generated": changelog_ok,
        "sync_details": sync_results,
    }
