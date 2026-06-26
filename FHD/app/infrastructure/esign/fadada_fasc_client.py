"""法大大 FASC 客户端（WIP stub）。

合同生命周期路由引用本模块，但实际实现尚未落地。
所有函数 raise NotImplementedError，命中路由时显式报错而非 ImportError。
落地实现时替换本文件即可。
"""

from __future__ import annotations

from typing import Any


def verify_fadada_callback_signature(headers: dict[str, str], biz_content: str) -> bool:
    """校验法大大回调签名。"""
    raise NotImplementedError("fadada_fasc_client 尚未实现：verify_fadada_callback_signature")


def parse_fadada_callback_biz(biz_content: str) -> dict[str, Any]:
    """解析法大大回调 bizContent 业务数据。"""
    raise NotImplementedError("fadada_fasc_client 尚未实现：parse_fadada_callback_biz")
