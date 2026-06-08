from __future__ import annotations

import os

from app.infrastructure.request_context.client_mods import get_request_client_mods_ui_off
from app.shell.xcagi_mods_discover import read_manifest_dicts


def extension_mod_manifest_rows() -> list[dict]:
    """磁盘上可路由扩展 manifest（排除占位 id / 显式 category|template 类型）。"""
    out: list[dict] = []
    for row in read_manifest_dicts():
        if not isinstance(row, dict):
            continue
        mid = str(row.get("id") or "").strip()
        if not mid or mid.lower() == "all":
            continue
        t = str(row.get("type") or "").strip().lower()
        if t in ("category", "template"):
            continue
        out.append(row)
    return out


def business_data_hidden_reason() -> str | None:
    if get_request_client_mods_ui_off():
        return "当前为「原版模式」（已发送 X-Client-Mods-Off），业务列表与扩展数据已隐藏。"
    flag = os.environ.get("FHD_BUSINESS_DATA_REQUIRES_EXTENSION_MOD", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        if not extension_mod_manifest_rows():
            return "未检测到可用的扩展 Mod；业务数据已按策略关闭。请配置 XCAGI_MODS_ROOT 并在 XCAGI/mods 下安装扩展后重试。"
    return None


def business_data_exposed() -> bool:
    return business_data_hidden_reason() is None
