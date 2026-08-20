# mypy: disable-error-code="assignment, attr-defined, no-any-return, valid-type"
# 成都修茈科技有限公司/MODstore_deploy/modstore_server/build_employee_pack.py
"""PR 合并后构建 employee_pack + 注册 + 触发审核。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

from modstore_server.evolution_ledger import append_event
from modstore_server.operational_errors import RECOVERABLE_ERRORS

try:  # Task 10 才会创建 evaluate_employee_pack，提前导入失败时降级
    from modstore_server.auto_approve_policy import evaluate_employee_pack
except ImportError:  # pragma: no cover - Task 10 未实现时
    evaluate_employee_pack = None

VALID_DEPARTMENTS = {"engineering", "quality", "ops", "growth", "support", "security"}
PACK_FILES_PREFIX = "成都修茈科技有限公司/MODstore_deploy/modstore_server/catalog_data/files/"
_PACK_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
_PACK_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")


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
    """Return exact changed paths without Git's quoted-path presentation layer."""

    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", f"{commit_sha}^..{commit_sha}"],
        cwd=str(repo_root),
        capture_output=True,
    )
    if result.returncode != 0:
        return []
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


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
    name = str(manifest.get("name") or "").strip()
    version = str(manifest.get("version") or "").strip()
    manifest_id = str(manifest.get("id") or name).strip()
    if not _PACK_NAME_RE.fullmatch(name) or manifest_id != name:
        raise PackSchemaError("manifest id/name must be the same safe package id")
    if not _PACK_VERSION_RE.fullmatch(version):
        raise PackSchemaError("manifest version must be semantic version")
    if manifest["department"] not in VALID_DEPARTMENTS:
        raise PackSchemaError(
            f"department must be one of {VALID_DEPARTMENTS}, got {manifest['department']}"
        )
    if not isinstance(manifest["skills"], list) or not isinstance(manifest["tools"], list):
        raise PackSchemaError("skills and tools must be lists")
    if not isinstance(manifest["acceptance_criteria"], list):
        raise PackSchemaError("acceptance_criteria must be list")


def build_xcemp_archive(manifest: Dict[str, Any], *, files_dir: Path) -> Path:
    """Build a deterministic, installable ``.xcemp`` beside the source directory."""

    validate_pack_schema(manifest)
    package_id = str(manifest["name"])
    version = str(manifest["version"])
    if not files_dir.is_dir():
        raise PackSchemaError(f"pack source directory not found: {files_dir}")
    source_files = sorted(
        path for path in files_dir.rglob("*") if path.is_file() and not path.is_symlink()
    )
    if not source_files:
        raise PackSchemaError("pack source directory is empty")
    archive = _catalog_files_root() / f"{package_id}-{version}.xcemp"
    tmp = archive.with_suffix(archive.suffix + ".tmp")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for source in source_files:
            relative = source.relative_to(files_dir)
            if ".." in relative.parts:
                raise PackSchemaError("pack source path escapes source directory")
            info = zipfile.ZipInfo(f"{package_id}/{relative.as_posix()}")
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            output.writestr(info, source.read_bytes())
    tmp.replace(archive)
    return archive


def register_in_packages_json(
    manifest: Dict[str, Any],
    *,
    files_dir: Path,
    archive_path: Path | None = None,
    source_commit_sha: str = "",
) -> str:
    """把 employee_pack 注册到 catalog_data/packages.json。"""
    validate_pack_schema(manifest)
    package_id = str(manifest["name"])
    version = str(manifest["version"])
    pack_key = f"{package_id}@{version}"
    catalog_path = _catalog_packages_path()
    if not catalog_path.is_file():
        data = {"schema": 1, "packages": []}
    else:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    packages = [
        row
        for row in data.get("packages", [])
        if not (
            str(row.get("id") or "") == pack_key
            or (str(row.get("id") or "") == package_id and str(row.get("version") or "") == version)
        )
    ]
    if archive_path is None:
        archive_path = build_xcemp_archive(manifest, files_dir=files_dir)
    if (
        not archive_path.is_file()
        or archive_path.parent.resolve() != _catalog_files_root().resolve()
    ):
        raise PackSchemaError("employee pack archive must be inside catalog files root")
    from modstore_server.catalog_store import sha256_file

    package_record = {
        "id": package_id,
        "name": package_id,
        "version": version,
        "description": str(manifest.get("description") or "")[:2000],
        "department": manifest["department"],
        "artifact": "employee_pack",
        "release_channel": "stable",
        "commerce": {"mode": "free", "price": 0},
        "license": {"type": "internal", "verify_url": None},
        "sha256": sha256_file(archive_path),
        "file_size": archive_path.stat().st_size,
        "stored_filename": archive_path.name,
        "employee_scope": "store",
        "employee_source": "autonomous_evolution",
        "is_duty_employee": False,
        "is_store_employee": True,
        "market_visible": True,
        "created_at": datetime.now(UTC).isoformat(),
    }
    clean_source_commit = str(source_commit_sha or "").strip().lower()
    if _COMMIT_RE.fullmatch(clean_source_commit):
        package_record["source_commit_sha"] = clean_source_commit
    packages.append(package_record)
    data["packages"] = packages
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return pack_key


def build_pack_from_commit(*, commit_sha: str, repo_root: Path) -> Dict[str, Any]:
    """PR 合并后从 commit diff 提取 employee_pack → 注册 → 触发审核。

    返回 {pack_id, approved, skipped, ...}。
    """
    diff_files = _get_commit_diff_files(commit_sha=commit_sha, repo_root=repo_root)
    pack_files = [f for f in diff_files if f.startswith(PACK_FILES_PREFIX)]
    manifest_files = [f for f in pack_files if f.endswith("/manifest.json")]
    if not manifest_files:
        return {"skipped": True, "reason": "no employee_pack files in commit diff"}

    # 提取 pack_id（路径形如 .../files/<pack_id>/manifest.json）
    first = pack_files[0]
    rel_after_prefix = first[len(PACK_FILES_PREFIX) :]
    pack_id = rel_after_prefix.split("/", 1)[0]

    # 读 manifest.json
    manifest_path = manifest_files[0]
    manifest = json.loads(_read_pack_file(manifest_path, repo_root))
    validate_pack_schema(manifest)
    if pack_id != f"{manifest['name']}@{manifest['version']}":
        raise PackSchemaError("pack source directory must be <name>@<version>")

    files_dir = _catalog_files_root() / pack_id
    if not files_dir.is_dir():
        raise PackSchemaError(f"pack source directory not found: {files_dir}")

    archive_path = build_xcemp_archive(manifest, files_dir=files_dir)

    # 注册
    pack_id_resolved = register_in_packages_json(
        manifest,
        files_dir=files_dir,
        archive_path=archive_path,
        source_commit_sha=commit_sha,
    )

    # 触发审核（Task 10 会实现 evaluate_employee_pack，测试里已 mock）
    try:
        if evaluate_employee_pack is None:  # Task 10 未实现
            raise RuntimeError("evaluate_employee_pack not implemented")
        risk_level, reason = evaluate_employee_pack(pack_id_resolved)
        approved = risk_level == "low"
    except RECOVERABLE_ERRORS as e:
        risk_level, reason = "high", f"evaluate_employee_pack failed: {e}"
        approved = False

    append_event(
        {
            "event_type": "pack_built" if approved else "pack_rejected",
            "event": "employee_pack_built" if approved else "employee_pack_rejected",
            "pack_id": pack_id_resolved,
            "package_id": str(manifest["name"]),
            "version": str(manifest["version"]),
            "package_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            "stored_filename": archive_path.name,
            "commit_sha": commit_sha,
            "risk_level": risk_level,
            "risk_reason": reason,
            "final_status": "pack_listed" if approved else "pack_rejected",
        }
    )

    return {
        "pack_id": pack_id_resolved,
        "package_id": str(manifest["name"]),
        "version": str(manifest["version"]),
        "package_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "stored_filename": archive_path.name,
        "source_commit_sha": (
            str(commit_sha).strip().lower()
            if _COMMIT_RE.fullmatch(str(commit_sha).strip().lower())
            else ""
        ),
        "approved": approved,
        "risk_level": risk_level,
        "reason": reason,
    }


__all__ = [
    "PackSchemaError",
    "validate_pack_schema",
    "build_xcemp_archive",
    "register_in_packages_json",
    "build_pack_from_commit",
]
