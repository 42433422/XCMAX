"""客户私有 Mod 控制面调用、产物下载、安装与版本更新。"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.infrastructure.mods.catalog_client import catalog_download_to, catalog_get_json
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_VERSION_TOKEN = re.compile(r"\d+|[A-Za-z]+")


def version_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """比较常见的 semver/内部版本，不依赖额外包。"""
    raw = str(value or "").strip().lstrip("vV")
    tokens: list[tuple[int, int | str]] = []
    for token in _VERSION_TOKEN.findall(raw):
        if token.isdigit():
            tokens.append((0, int(token)))
        else:
            tokens.append((1, token.lower()))
    return tuple(tokens) or ((0, 0),)


def is_newer_version(remote: str, local: str) -> bool:
    return bool(str(remote or "").strip()) and version_key(remote) > version_key(local)


def _auth_header(token: str) -> str:
    raw = str(token or "").strip()
    return raw if raw.lower().startswith("bearer ") else f"Bearer {raw}"


async def custom_delivery_remote_json(
    market_token: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """调用 MODstore 定制交付控制面，始终使用当前市场账号令牌。"""
    token = str(market_token or "").strip()
    if not token:
        raise PermissionError("缺少市场登录凭证")
    from app.fastapi_routes.market_account import _market_base_url

    clean = path if str(path or "").startswith("/") else f"/{path}"
    url = f"{_market_base_url()}{clean}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=8.0)) as client:
            response = await client.request(
                method.upper(),
                url,
                headers={"Authorization": _auth_header(token)},
                json=payload if payload is not None else None,
            )
    except httpx.RequestError as exc:
        raise ConnectionError(f"MODstore 定制交付服务不可达：{exc}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400:
        detail = ""
        if isinstance(body, dict):
            detail = str(body.get("detail") or body.get("message") or "").strip()
        raise RuntimeError(detail or f"MODstore 返回 HTTP {response.status_code}")
    if not isinstance(body, dict):
        raise RuntimeError("MODstore 定制交付返回格式无效")
    return body


async def install_custom_delivery_artifact(
    market_token: str,
    ticket_id: int,
    artifact_kind: str,
) -> dict[str, Any]:
    """下载已验收的账号私有产物，安装成功后再回写交付回执。"""
    token = str(market_token or "").strip()
    kind = str(artifact_kind or "").strip()
    if kind not in {"module", "employee"}:
        raise ValueError("artifact_kind 必须是 module 或 employee")
    from app.fastapi_routes.market_account import _market_base_url

    url = (
        f"{_market_base_url()}/api/customer-service/custom-deliveries/"
        f"{int(ticket_id)}/artifacts/{kind}/download"
    )
    tmp = tempfile.NamedTemporaryFile(prefix="xcagi-custom-delivery-", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=8.0)) as client:
                response = await client.get(
                    url,
                    headers={"Authorization": _auth_header(token)},
                )
        except httpx.RequestError as exc:
            raise ConnectionError(f"定制产物下载失败：{exc}") from exc
        if response.status_code >= 400:
            try:
                err = response.json()
            except ValueError:
                err = {}
            detail = str(err.get("detail") or "").strip() if isinstance(err, dict) else ""
            raise RuntimeError(detail or f"定制产物下载返回 HTTP {response.status_code}")
        receipt_token = str(response.headers.get("X-Delivery-Receipt-Token") or "").strip()
        if len(receipt_token) < 16:
            raise RuntimeError("定制产物缺少安装回执凭证")
        tmp_path.write_bytes(response.content)
        if not response.content:
            raise RuntimeError("定制产物包为空")

        artifact_id = ""
        installed_version = ""
        if kind == "employee":
            from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK
            from app.infrastructure.mods.artifact_package import peek_artifact
            from app.infrastructure.mods.employee_registry import get_employee_registry

            if peek_artifact(str(tmp_path)) != ARTIFACT_EMPLOYEE_PACK:
                raise ValueError("产物类型校验失败：期望 AI 员工包")
            ok, message = get_employee_registry().install_from_package(
                str(tmp_path), verify_signature=True
            )
            if not ok:
                raise RuntimeError(message)
            import zipfile

            with zipfile.ZipFile(tmp_path) as archive:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            artifact_id = str(manifest.get("id") or "").strip()
            installed_version = str(manifest.get("version") or "").strip()
        else:
            from app.infrastructure.mods.mod_manager import get_mod_manager
            from app.infrastructure.mods.package import ModPackage

            with tempfile.TemporaryDirectory(prefix="xcagi-custom-delivery-check-") as check_dir:
                _, manifest = ModPackage.extract_package(
                    str(tmp_path), check_dir, verify_signature=True
                )
            artifact_id = str(manifest.get("id") or "").strip()
            installed_version = str(manifest.get("version") or "").strip()
            ok, message, metadata = get_mod_manager().install_mod_package(
                str(tmp_path), verify_signature=True, activate=True
            )
            if not ok:
                raise RuntimeError(message)
            try:
                from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

                ensure_mod_api_ready(artifact_id)
            except RECOVERABLE_ERRORS:
                logger.warning("定制 Mod %s API 路由刷新失败", artifact_id, exc_info=True)
            installed_version = str(getattr(metadata, "version", "") or installed_version)
        if not artifact_id:
            raise ValueError("定制产物缺少 ID")

        receipt = await custom_delivery_remote_json(
            token,
            f"/api/customer-service/custom-deliveries/{int(ticket_id)}/installed",
            method="POST",
            payload={
                "artifact_kind": kind,
                "artifact_id": artifact_id,
                "installed_version": installed_version,
                "host": "XCAGI Desktop",
                "receipt_token": receipt_token,
            },
        )
        return {
            "success": True,
            "artifact_kind": kind,
            "artifact_id": artifact_id,
            "installed_version": installed_version,
            "message": "定制产物已安装并回写交付回执",
            "delivery": receipt,
        }
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "custom_delivery_remote_json",
    "fetch_private_mod_library",
    "install_custom_delivery_artifact",
    "is_newer_version",
    "update_private_mod_from_library",
    "version_key",
]


async def fetch_private_mod_library(market_token: str) -> list[dict[str, Any]]:
    token = str(market_token or "").strip()
    if not token:
        return []
    payload = await catalog_get_json(
        "/v1/mod-sync/mods",
        headers={"Authorization": _auth_header(token)},
    )
    raw = payload.get("data")
    if not isinstance(raw, list):
        raw = payload.get("mods")
    return [dict(row) for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def _library_row_by_id(rows: list[dict[str, Any]], mod_id: str) -> dict[str, Any] | None:
    target = str(mod_id or "").strip()
    for row in rows:
        if str(row.get("id") or "").strip() == target:
            return row
    return None


async def update_private_mod_from_library(
    mod_id: str,
    market_token: str,
    *,
    expected_version: str = "",
) -> dict[str, Any]:
    """从账号私有 Mod 库下载并安装最新 Mod。"""
    mid = str(mod_id or "").strip()
    if not mid or "/" in mid or "\\" in mid:
        raise ValueError("非法客户 Mod id")
    rows = await fetch_private_mod_library(market_token)
    remote = _library_row_by_id(rows, mid)
    if not remote:
        raise LookupError("当前账号没有该客户 Mod 的私有版本")
    remote_version = str(remote.get("version") or "").strip()
    if not remote_version:
        raise ValueError("私有 Mod 版本信息缺失")
    if expected_version and expected_version != remote_version:
        raise ValueError("私有 Mod 版本已变化，请刷新后重试")

    from app.infrastructure.mods.mod_manager import get_mod_manager

    manager = get_mod_manager()
    local = next(
        (m for m in manager.scan_mods(use_cache=False) if str(m.id or "").strip() == mid),
        None,
    )
    local_version = str(local.version or "") if local else ""
    if local and not is_newer_version(remote_version, local_version):
        return {
            "success": True,
            "updated": False,
            "mod_id": mid,
            "current_version": local_version,
            "latest_version": remote_version,
            "message": "当前已是私有 Mod 最新版本",
        }

    token = str(market_token or "").strip()
    if not token:
        raise PermissionError("缺少市场登录凭证，无法更新客户私有 Mod")
    tmp = tempfile.NamedTemporaryFile(prefix="xcagi-private-mod-", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        await catalog_download_to(
            f"/v1/mod-sync/export-zip/{quote(mid, safe='')}",
            tmp_path,
            headers={"Authorization": _auth_header(token)},
        )
        from app.infrastructure.mods.package import ModPackage

        with tempfile.TemporaryDirectory(prefix="xcagi-private-mod-check-") as check_dir:
            _, manifest = ModPackage.extract_package(
                str(tmp_path), check_dir, verify_signature=True
            )
        manifest_id = str(manifest.get("id") or "").strip()
        manifest_version = str(manifest.get("version") or "").strip()
        if manifest_id != mid:
            raise ValueError("私有 Mod 包身份校验失败")
        if manifest_version and manifest_version != remote_version:
            raise ValueError("私有 Mod 包版本与私有目录不一致")

        ok, message, metadata = manager.install_mod_package(
            str(tmp_path), verify_signature=True, activate=True
        )
        if not ok:
            raise RuntimeError(message)
        try:
            from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

            ensure_mod_api_ready(mid)
        except RECOVERABLE_ERRORS:
            logger.warning("私有 Mod %s API 路由刷新失败", mid, exc_info=True)
        return {
            "success": True,
            "updated": True,
            "mod_id": mid,
            "previous_version": local_version,
            "current_version": str(getattr(metadata, "version", "") or remote_version),
            "latest_version": remote_version,
            "message": message,
        }
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
