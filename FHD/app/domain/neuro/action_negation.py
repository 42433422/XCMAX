"""Recognize denied actions before deterministic or model-driven planning."""

import re

_DENIED_ACTION = re.compile(
    r"(?:不要|别|不用|不需要|暂不|先不|停止|取消)(?!忘记|忘了)"
    r"[^，,。；;]{0,8}(?:打印|开单|打单|发货|送货|出货|删除|移除|下单|入库|出库|导入|发送)"
)


def has_denied_action(message: str) -> bool:
    return bool(_DENIED_ACTION.search(str(message or "")))
