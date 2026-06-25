"""自建电子签任务存储（WIP stub）。

合同生命周期路由引用本模块，但实际实现尚未落地。
所有函数 raise NotImplementedError，命中路由时显式报错而非 ImportError。
落地实现时替换本文件即可。
"""

from __future__ import annotations

from typing import Any


def get_task(task_id: str) -> dict[str, Any] | None:
    """按 task_id 查询签署任务，不存在返回 None。"""
    raise NotImplementedError("stub_esign_store 尚未实现：get_task")


def task_ttl_exceeded(task: dict[str, Any]) -> bool:
    """判断签署任务是否超过 TTL。"""
    raise NotImplementedError("stub_esign_store 尚未实现：task_ttl_exceeded")


def verify_sign_token(task_id: str, token: str) -> bool:
    """校验签署链接 token 是否有效。"""
    raise NotImplementedError("stub_esign_store 尚未实现：verify_sign_token")


def complete_task(task_id: str, *, signer_name: str) -> None:
    """标记签署任务为已完成。"""
    raise NotImplementedError("stub_esign_store 尚未实现：complete_task")
