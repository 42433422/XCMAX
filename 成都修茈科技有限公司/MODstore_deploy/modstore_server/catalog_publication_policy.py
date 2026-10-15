"""Explicit public classification and ordered stable catalog versions."""

from __future__ import annotations

import re
from typing import Any


def stable_version(value: Any) -> tuple[int, ...]:
    text = str(value or "").strip()
    if not re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?", text
    ):
        raise ValueError("自动发布须使用三段或四段数字稳定版本；源码变更须提升 manifest.version")
    parts = tuple(int(part) for part in text.split("."))
    return parts + (0,) * (4 - len(parts))


def is_private_package(record: dict[str, Any]) -> bool:
    return (
        record.get("artifact") == "customer_delivery_seed"
        or str(record.get("visibility") or "").lower() in {"private", "customer", "internal"}
        or record.get("public_listing") is False
        or any(
            record.get(key)
            for key in (
                "customer_account",
                "account_mod_id",
                "owner_id",
                "owner_user_id",
                "customer_id",
                "tenant_id",
            )
        )
    )


def require_public_manifest(manifest: dict[str, Any]) -> None:
    if is_private_package(manifest) or manifest.get("public_listing") is not True:
        raise ValueError(
            "通用发布仅接受显式 public_listing=true 的公开包；客户私包须走已绑定 owner 的工单生产中心"
        )
