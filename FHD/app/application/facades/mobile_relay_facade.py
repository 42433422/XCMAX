"""移动中继域门面：路由层通过本门面访问移动中继服务，不直接依赖 app.services。"""

from app.services.mobile_relay_desktop_client import register_desktop_relay
from app.services.mobile_relay_service import MobileRelayService

__all__ = [
    "MobileRelayService",
    "register_desktop_relay",
]
