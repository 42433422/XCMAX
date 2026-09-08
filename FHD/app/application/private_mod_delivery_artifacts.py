"""客户私有 Mod 控制面调用、产物下载、安装与版本更新。"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

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
    *,
    owner_scope: str = "",
    artifact_id: str = "",
) -> dict[str, Any]:
    """下载已验收的账号私有产物，安装成功后再回写交付回执。"""
    token = str(market_token or "").strip()
    kind = str(artifact_kind or "").strip()
    requested_id = str(artifact_id or "").strip()
    if kind not in {"module", "employee"}:
        raise ValueError("artifact_kind 必须是 module 或 employee")
    if not token:
        raise PermissionError("缺少市场登录凭证")
    if not owner_scope:
        raise ValueError("定制产物安装必须绑定当前工作空间")
    from app.fastapi_routes.market_account import _market_base_url

    url = (
        f"{_market_base_url()}/api/customer-service/custom-deliveries/"
        f"{int(ticket_id)}/artifacts/{kind}/download"
    )
    if requested_id:
        url += "?" + urlencode({"artifact_id": requested_id})
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
        package_sha256 = hashlib.sha256(response.content).hexdigest()
        expected_sha256 = str(response.headers.get("X-Delivery-Artifact-SHA256") or "").strip()
        expected_version = str(response.headers.get("X-Delivery-Artifact-Version") or "").strip()
        if package_sha256 != expected_sha256 or not expected_version:
            raise RuntimeError("定制产物摘要或版本凭证缺失、不匹配")
        tmp_path.write_bytes(response.content)
        if not response.content:
            raise RuntimeError("定制产物包为空")

        artifact_id = ""
        installed_version = ""
        from app.infrastructure.mods.package_signing import verify_signed_package_bytes

        signed = verify_signed_package_bytes(response.content)
        manifest = signed["manifest"]
        artifact_id = str(manifest.get("id") or "").strip()
        installed_version = str(manifest.get("version") or "").strip()
        if not artifact_id or installed_version != expected_version:
            raise RuntimeError("定制产物身份或版本与下载凭证不匹配")
        if requested_id and artifact_id != requested_id:
            raise RuntimeError("定制产物身份与所选交付项目不匹配")
        from app.application.mod_delivery_receipt_outbox import record_installed_delivery

        def persist_grant() -> str:
            return record_installed_delivery(
                owner=owner_scope,
                ticket_id=ticket_id,
                artifact_kind=kind,
                artifact_id=artifact_id,
                version=installed_version,
                package_sha256=package_sha256,
                receipt_token=receipt_token,
            )

        receipt_id = ""
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
        else:
            from app.infrastructure.mods.mod_manager import get_mod_manager
            from app.infrastructure.mods.package import ModPackage

            with tempfile.TemporaryDirectory(prefix="xcagi-custom-delivery-check-") as check_dir:
                _, manifest = ModPackage.extract_package(
                    str(tmp_path), check_dir, verify_signature=True
                )
            artifact_id = str(manifest.get("id") or "").strip()
            installed_version = str(manifest.get("version") or "").strip()
            if installed_version != expected_version:
                raise RuntimeError("定制产物版本与下载凭证不匹配")
            # Persist the grant before mutation; the sender separately verifies
            # the actual installation, including recovery after process death.
            receipt_id = persist_grant()
            ok, message, metadata = get_mod_manager().install_mod_package(
                str(tmp_path), verify_signature=True, activate=True, owner_scope=owner_scope
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

        if installed_version != expected_version:
            raise RuntimeError("定制产物版本与下载凭证不匹配")
        if not receipt_id:
            receipt_id = persist_grant()
        return {
            "success": True,
            "artifact_kind": kind,
            "artifact_id": artifact_id,
            "installed_version": installed_version,
            "package_sha256": package_sha256,
            "receipt_id": receipt_id,
            "runtime_verified": False,
            "message": "定制产物已安装，等待运行与业务验证回执",
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
    owner_scope: str = "",
    require_account_scope: bool = False,
) -> dict[str, Any]:
    """从账号私有 Mod 库下载并安装最新 Mod。"""
    mid = str(mod_id or "").strip()
    if not mid or "/" in mid or "\\" in mid:
        raise ValueError("非法客户 Mod id")
    if not owner_scope:
        raise ValueError("私有 Mod 更新必须绑定当前工作空间")
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
        download_headers = httpx.Headers(
            await catalog_download_to(
                f"/v1/mod-sync/export-zip/{quote(mid, safe='')}",
                tmp_path,
                headers={"Authorization": _auth_header(token)},
            )
        )
        expected_digest = str(remote.get("package_sha256") or remote.get("sha256") or "").strip()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
            or hashlib.sha256(tmp_path.read_bytes()).hexdigest() != expected_digest
        ):
            raise ValueError("私有 Mod 包摘要与私有目录不一致")
        receipt_token = download_headers.get("X-Delivery-Receipt-Token", "")
        ticket_id = int(download_headers.get("X-Delivery-Ticket-ID", "0"))
        if (
            ticket_id <= 0
            or len(receipt_token) < 16
            or download_headers.get("X-Delivery-Artifact-SHA256") != expected_digest
            or download_headers.get("X-Delivery-Artifact-Version") != remote_version
        ):
            raise ValueError("私有 Mod 更新缺少匹配的工单交付凭证")
        declared_ticket = remote.get("delivery_ticket_id")
        if declared_ticket is not None and int(declared_ticket) != ticket_id:
            raise ValueError("私有 Mod 更新工单与私有目录不一致")
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
        if require_account_scope and manifest.get("scope") != "account":
            raise ValueError("自动私有交付只能安装声明账号作用域的签名包")

        from app.application.mod_delivery_receipt_outbox import record_installed_delivery

        receipt_id = record_installed_delivery(
            owner=owner_scope,
            ticket_id=ticket_id,
            artifact_kind="module",
            artifact_id=mid,
            version=manifest_version,
            package_sha256=expected_digest,
            receipt_token=receipt_token,
        )
        ok, message, metadata = manager.install_mod_package(
            str(tmp_path), verify_signature=True, activate=True, owner_scope=owner_scope
        )
        if not ok:
            raise RuntimeError(message)
        from app.infrastructure.mods.install_receipts import read_verified_install

        receipt = read_verified_install(mid, mods_root=manager.mods_root)
        restart = bool(receipt and receipt.get("requires_restart"))
        try:
            from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

            if not restart:
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
            "requires_restart": restart,
            "runtime_status": "restart_required" if restart else "installed",
            "receipt_id": receipt_id,
            "delivery_ticket_id": ticket_id,
            "message": message,
        }
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
