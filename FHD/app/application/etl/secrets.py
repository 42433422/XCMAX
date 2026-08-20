"""Webhook 凭据存储。

数据库只持有不透明 ``secret_ref``；真实值交给 macOS Keychain / Windows
Credential Manager 的 keyring 后端。后端不可用时严格失败。
"""

from __future__ import annotations

import os
import uuid
from typing import cast

from app.application.etl.errors import EtlError
from app.utils.operational_errors import RECOVERABLE_ERRORS

_SERVICE_NAME = "com.xcagi.fhd.etl"


def store_webhook_secret(owner_user_id: int, secret: str) -> str:
    if not secret:
        raise EtlError("ETL_SECRET_EMPTY", "Webhook 密钥不能为空")
    try:
        import keyring
    except ImportError as exc:
        raise EtlError(
            "ETL_CREDENTIAL_STORE_UNAVAILABLE",
            "系统凭据管理器不可用，Webhook 配置未保存",
            status_code=503,
        ) from exc
    ref = f"etl:{owner_user_id}:{uuid.uuid4()}"
    try:
        keyring.set_password(_SERVICE_NAME, ref, secret)
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - 不返回系统异常细节
        raise EtlError(
            "ETL_CREDENTIAL_STORE_WRITE_FAILED",
            "系统凭据管理器写入失败，Webhook 配置未保存",
            status_code=503,
        ) from exc
    return ref


def read_webhook_secret(secret_ref: str | None) -> str:
    ref = str(secret_ref or "").strip()
    if not ref:
        return ""
    # 仅供部署时注入轮换密钥，不允许客户端指定任意环境变量名。
    if ref.startswith("env:FHD_ETL_WEBHOOK_SECRET_"):
        value = os.environ.get(ref[4:], "")
        if value:
            return value
        raise EtlError(
            "ETL_CREDENTIAL_UNAVAILABLE", "Webhook 凭据无法读取，已拒绝发送", status_code=503
        )
    try:
        import keyring

        value = keyring.get_password(_SERVICE_NAME, ref)
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
        raise EtlError(
            "ETL_CREDENTIAL_UNAVAILABLE", "Webhook 凭据无法读取，已拒绝发送", status_code=503
        ) from exc
    if not value:
        raise EtlError(
            "ETL_CREDENTIAL_UNAVAILABLE", "Webhook 凭据无法读取，已拒绝发送", status_code=503
        )
    return cast("str", value)


def delete_webhook_secret(secret_ref: str | None) -> None:
    ref = str(secret_ref or "").strip()
    if not ref or ref.startswith("env:"):
        return
    try:
        import keyring

        keyring.delete_password(_SERVICE_NAME, ref)
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - 删除配置不泄露后端信息
        return
