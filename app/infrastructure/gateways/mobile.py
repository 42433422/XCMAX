"""移动端推送网关。"""

from __future__ import annotations

from typing import Any


def notify_user(*args: Any, **kwargs: Any) -> Any:
    from app.services.mobile_push import notify_user as _f

    return _f(*args, **kwargs)


__all__ = ["notify_user"]
