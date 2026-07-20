# 成都修茈科技有限公司/MODstore_deploy/modstore_server/build_employee_pack.py
"""PR 合并后构建 employee_pack + 注册 + 触发审核。"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from modstore_server.evolution_ledger import append_event

try:  # Task 10 才会创建 evaluate_employee_pack，提前导入失败时降级
    from modstore_server.auto_approve_policy import evaluate_employee_pack
except ImportError:  # pragma: no cover - Task 10 未实现时
    evaluate_employee_pack = None

VALID_DEPARTMENTS = {"engineering", "quality", "ops", "growth", "support", "security"}
PACK_FILES_PREFIX = "成都修茈科技有限公司/MODstore_deploy/catalog_data/files/"


class PackSchemaError(ValueError):
    """employee_pack schema 校验失败。"""


def _catalog_packages_path() -> Path:
    env_val = os.environ.get("MODSTORE_CATALOG_PACKAGES_PATH", "")
    if env_val:
        return Path(env_val)
    from modstore_server.evolution_signal_collector import _repo_root

    return (
        Path(_repo_root())
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "modstore_server"
        / "catalog_data"
        / "packages.json"
    )


def _catalog_files_root() -> Path:
    env_val = os.environ.get("MODSTORE_CATALOG_FILES_ROOT", "")
    if env_val:
        return Path(env_val)
    from modstore_server.evolution_signal_collector import _repo_root

    return (
        Path(_repo_root())
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "modstore_server"
        / "catalog_data"
        / "files"
    )


def _get_commit_diff_files(*, commit_sha: str, repo_root: Path) -> List[str]:
    """git diff --name-only <commit>^..<commit>"""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{commit_sha}^..{commit_sha}"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _read_pack_file(rel_path: str, repo_root: Path) -> str:
    return (repo_root / rel_path).read_text(encoding="utf-8")


def validate_pack_schema(manifest: Dict[str, Any]) -> None:
    """校验 employee_pack manifest。"""
    if not isinstance(manifest, dict):
        raise PackSchemaError("manifest must be dict")
    required = [
        "name",
        "version",
        "department",
        "prompt_template",
        "skills",
        "tools",
        "acceptance_criteria",
    ]
    for key in required:
        if key not in manifest:
            raise PackSchemaError(f"manifest missing field: {key}")
    if manifest["department"] not in VALID_DEPARTMENTS:
        raise PackSchemaError(
            f"department must be one of {VALID_DEPARTMENTS}, got {manifest['department']}"
        )
    if not isinstance(manifest["skills"], list) or not isinstance(manifest["tools"], list):
        raise PackSchemaError("skills and tools must be lists")


def register_in_packages_json(manifest: Dict[str, Any], *, files_dir: Path) -> str:
    """把 employee_pack 注册到 catalog_data/packages.json。"""
    pack_id = f"{manifest['name']}@{manifest['version']}"
    catalog_path = _catalog_packages_path()
    if not catalog_path.is_file():
        data = {"schema": 1, "packages": []}
    else:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    for existing in data.get("packages", []):
        if existing.get("id") == pack_id:
            raise PackSchemaError(f"duplicate pack_id: {pack_id}")
    try:
        files_dir_value = str(files_dir.relative_to(_catalog_files_root().parent))
    except ValueError:
        # files_dir 不在 catalog_files_root 下（如测试隔离场景），退化为绝对/原值
        files_dir_value = str(files_dir)
    data.setdefault("packages", []).append(
        {
            "id": pack_id,
            "name": manifest["name"],
            "version": manifest["version"],
            "department": manifest["department"],
            "files_dir": files_dir_value,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return pack_id


def build_pack_from_commit(*, commit_sha: str, repo_root: Path) -> Dict[str, Any]:
    """PR 合并后从 commit diff 提取 employee_pack → 注册 → 触发审核。

    返回 {pack_id, approved, skipped, ...}。
    """
    diff_files = _get_commit_diff_files(commit_sha=commit_sha, repo_root=repo_root)
    pack_files = [f for f in diff_files if f.startswith(PACK_FILES_PREFIX)]
    if not pack_files:
        return {"skipped": True, "reason": "no employee_pack files in commit diff"}

    # 提取 pack_id（路径形如 .../files/<pack_id>/manifest.json）
    first = pack_files[0]
    rel_after_prefix = first[len(PACK_FILES_PREFIX) :]
    pack_id = rel_after_prefix.split("/", 1)[0]

    # 读 manifest.json
    manifest_path = next(f for f in pack_files if f.endswith("manifest.json"))
    manifest = json.loads(_read_pack_file(manifest_path, repo_root))
    validate_pack_schema(manifest)

    files_dir = _catalog_files_root() / pack_id
    files_dir.mkdir(parents=True, exist_ok=True)

    # 注册
    pack_id_resolved = register_in_packages_json(manifest, files_dir=files_dir)

    # 触发审核（Task 10 会实现 evaluate_employee_pack，测试里已 mock）
    try:
        if evaluate_employee_pack is None:  # Task 10 未实现
            raise RuntimeError("evaluate_employee_pack not implemented")
        risk_level, reason = evaluate_employee_pack(pack_id_resolved)
        approved = risk_level == "low"
    except Exception as e:
        risk_level, reason = "high", f"evaluate_employee_pack failed: {e}"
        approved = False

    append_event(
        {
            "event_type": "pack_built" if approved else "pack_rejected",
            "pack_id": pack_id_resolved,
            "commit_sha": commit_sha,
            "risk_level": risk_level,
            "risk_reason": reason,
            "final_status": "pack_listed" if approved else "pack_rejected",
        }
    )

    return {
        "pack_id": pack_id_resolved,
        "approved": approved,
        "risk_level": risk_level,
        "reason": reason,
    }


__all__ = [
    "PackSchemaError",
    "validate_pack_schema",
    "register_in_packages_json",
    "build_pack_from_commit",
]
