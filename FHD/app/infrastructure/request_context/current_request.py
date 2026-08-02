"""向后兼容 shim：实现已下沉至 ``app.domain.context.current_request``。

ContextVar 持有器属于纯领域关切（domain 层 ``value_objects_industry`` 直接读取），
infrastructure 仅做 re-export，历史 import 路径保持不变。
"""

from app.domain.context.current_request import (
    get_current_request,
    reset_current_request,
    set_current_request,
)

__all__ = [
    "get_current_request",
    "reset_current_request",
    "set_current_request",
]
