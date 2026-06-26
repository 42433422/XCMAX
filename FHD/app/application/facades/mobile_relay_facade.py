"""移动中继域门面：路由层通过本门面访问移动中继服务，不直接依赖 app.services。"""

from typing import Any

from app.services.mobile_relay_service import MobileRelayService


def register_desktop_relay(*, host: str, port: int) -> dict[str, Any]:
    from app.services.mobile_relay_desktop_client import register_desktop_relay as _register

    return _register(host=host, port=port)


def cached_desktop_relay_payload() -> dict[str, Any] | None:
    from app.services.mobile_relay_desktop_client import cached_desktop_relay_payload as _cached

    return _cached()


__all__ = [
    "MobileRelayService",
    "cached_desktop_relay_payload",
    "register_desktop_relay",
]
