"""电子签适配器（WIP stub）。

合同生命周期路由引用本模块，但实际实现尚未落地。
所有函数 raise NotImplementedError，命中路由时显式报错而非 ImportError。
落地实现时替换本文件即可。
"""

from __future__ import annotations

from typing import Any


def esign_channel_status() -> dict[str, Any]:
    """返回当前电子签通道状态（provider / 是否可用等）。"""
    raise NotImplementedError("esign_adapter 尚未实现：esign_channel_status")


def esign_provider_name() -> str:
    """返回当前电子签供应商标识（如 'stub' / 'fadada'）。"""
    raise NotImplementedError("esign_adapter 尚未实现：esign_provider_name")


class EsignAdapter:
    """电子签适配器协议：解析 webhook 回调。"""

    def parse_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("esign_adapter 尚未实现：EsignAdapter.parse_webhook")


def get_esign_adapter() -> EsignAdapter:
    """返回当前通道的电子签适配器实例。"""
    raise NotImplementedError("esign_adapter 尚未实现：get_esign_adapter")
