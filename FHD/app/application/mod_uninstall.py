"""Authenticated, owner-scoped removal of locally installed Mods."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from app.application.tenant_workspace_prefs import resolve_workspace_owner_id
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.infrastructure.mods import install_receipts
from app.infrastructure.mods.state_lock import state_lock


def _is_admin(user: object) -> bool:
    """Match the host's verified admin dependency; market flags are not roles."""
    return str(getattr(user, "tier", "") or "").strip() == "admin"


def _read_manifest(directory: Path, mod_id: str) -> dict[str, Any] | None:
    if directory.is_symlink() or not directory.is_dir():
        return None
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    declared_id = str(manifest.get("id") or "").strip()
    if declared_id and declared_id != mod_id:
        return None
    return manifest


def _is_global_or_legacy_manifest(manifest: dict[str, Any] | None) -> bool:
    if not manifest:
        return False
    scope = str(manifest.get("scope") or "").strip().lower()
    if scope not in {"", "global"}:
        return False
    if str(manifest.get("entitlement_mod_id") or "").strip():
        return False
    if "public_listing" in manifest and manifest["public_listing"] is not True:
        return False
    if str(manifest.get("visibility") or "").strip().lower() not in {"", "public", "global"}:
        return False
    if any(manifest.get(key) for key in ("owner_scope", "owner_user_id", "delivery_owner_user_id")):
        return False
    return True


def _manifest_for_legacy_install(root: Path, mod_id: str) -> dict[str, Any] | None:
    # Employee packs use the host-global _employees directory; regular Mods use
    # the host Mod root. Neither path is selected by caller-supplied owner data.
    for directory in (root / mod_id, root / "_employees" / mod_id):
        manifest = _read_manifest(directory, mod_id)
        if manifest is not None:
            return manifest
    return None


def uninstall_mod_for_request(request: Request, mod_id: str) -> tuple[bool, str]:
    """Authorize and perform the same local uninstall for both host API routes.

    Account-owned signed installs are removable only by their bound owner. An
    unowned global/legacy install is an explicit administrator-only operation.
    A present but unverifiable receipt fails closed for every role.
    """
    user = get_logged_in_user(request)
    owner = resolve_workspace_owner_id(request, user)
    admin = _is_admin(user)
    if not owner and not admin:
        raise HTTPException(status_code=403, detail="无法确认扩展安装归属")

    mod_id = str(mod_id or "").strip()
    if not mod_id:
        raise HTTPException(status_code=400, detail="缺少 mod_id")

    from app.infrastructure.mods.mod_manager import get_mod_manager, get_mod_registry

    manager = get_mod_manager()
    root = install_receipts._root(str(manager.mods_root))
    try:
        state = install_receipts._state_dir(root, mod_id)
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="无效的扩展包编号") from None

    receipt_path = state / "receipt.json"
    pending_to_remove: tuple[Path, str] | None = None
    verified_regular_root: Path | None = None
    try:
        # Keep the same lock order as install_receipts.install_extracted and
        # pending activation: process-wide install lock, then per-Mod file lock.
        with install_receipts._LOCK, state_lock(state):
            if (root / mod_id).exists() and (root / "_employees" / mod_id).exists():
                raise HTTPException(status_code=409, detail="扩展安装位置存在歧义，拒绝卸载")
            if receipt_path.is_symlink():
                raise HTTPException(status_code=409, detail="安装收据路径无效，拒绝卸载")

            if receipt_path.exists():
                install = install_receipts.read_verified_install(mod_id, mods_root=str(root))
                if not install:
                    raise HTTPException(status_code=409, detail="安装收据或签名校验失败，拒绝卸载")

                installed_owner = str(install.get("owner_scope") or "").strip()
                if installed_owner:
                    if installed_owner != owner:
                        raise HTTPException(status_code=403, detail="当前账号无权卸载此账号扩展")
                else:
                    manifest = _read_manifest(
                        Path(str(install.get("installed_root") or "")), mod_id
                    )
                    if not admin or not _is_global_or_legacy_manifest(manifest):
                        raise HTTPException(
                            status_code=403, detail="扩展归属或卸载权限未通过校验，拒绝删除"
                        )
                if not install.get("requires_restart"):
                    verified_regular_root = Path(str(install["installed_root"]))
                if install.get("requires_restart"):
                    pending_to_remove = (
                        Path(str(install.get("installed_root") or "")),
                        str(install.get("package_sha256") or ""),
                    )
            else:
                manifest = _manifest_for_legacy_install(root, mod_id)
                if not manifest:
                    # Preserve the endpoints' existing not-found response shape;
                    # do not let a stale in-memory registry entry become authority.
                    return False, f"MOD {mod_id} 未加载或不存在"
                if not admin or not _is_global_or_legacy_manifest(manifest):
                    raise HTTPException(
                        status_code=403, detail="旧包归属或卸载权限未通过校验，拒绝删除"
                    )

            result: tuple[bool, str]
            if (
                verified_regular_root is not None
                and get_mod_registry().get_mod_metadata(mod_id) is None
            ):
                # A verified disk install need not have loaded successfully. Never
                # apply this fallback to unsigned legacy or unverified pending trees.
                manager.unload_mod(mod_id)
                shutil.rmtree(verified_regular_root)
                result = (True, f"MOD {mod_id} 卸载成功")
            else:
                result = manager.uninstall_mod(mod_id, remove_files=True)
            if not result[0]:
                return result

            # A hot update may be staged beside the active directory. Remove
            # only the verified pending tree while holding the same install lock.
            if pending_to_remove is not None:
                pending, digest = pending_to_remove
                expected_parent = state.resolve()
                if (
                    not pending.is_symlink()
                    and pending.parent.resolve() == expected_parent
                    and pending.name == "pending-" + digest
                ):
                    shutil.rmtree(pending)
            return result
    except HTTPException:
        raise
    except OSError:
        raise HTTPException(status_code=409, detail="扩展正在安装或卸载，请稍后重试") from None
