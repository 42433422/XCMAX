"""共享运行模块内的客户定制功能授权；以有效请求会话为边界。"""

from fastapi import HTTPException, Request

from app.enterprise.private_delivery_binding import load_session_private_delivery_binding
from app.infrastructure.auth.dependencies import get_logged_in_user, session_id_from_request
from app.mod_sdk.customer_delivery import delivery_for_account


def _enterprise_desktop_attendance(request: Request, username: str) -> bool:
    """Enterprise desktop sessions entitled to the industry pack may convert attendance."""
    from app.enterprise.account_mod_binding import (
        augment_entitled_client_mod_ids_for_username,
        is_enterprise_demo_local_username,
    )
    from app.mod_sdk.product_plane import is_enterprise_client_plane

    if not is_enterprise_client_plane():
        return False
    if is_enterprise_demo_local_username(username):
        return True
    mods = augment_entitled_client_mod_ids_for_username(username, set())
    return "attendance-industry" in mods


def attendance_custom_features(request: Request) -> dict:
    user = get_logged_in_user(request)
    binding = load_session_private_delivery_binding(session_id_from_request(request))
    username = str(getattr(user, "username", "") or binding.get("username", "") or "")
    delivery = delivery_for_account(binding.get("username", "")) or {}
    granted = (
        binding.get("market_user_id")
        and delivery.get("delivery_mode") == "private_mod"
        and delivery.get("runtime_mod_id") == "sunbird-attendance-custom"
        and delivery.get("legacy_mod_id") in binding.get("mod_ids", set())
    )
    features = list(delivery.get("custom_features") or []) if granted else []
    delivery_id = delivery.get("legacy_mod_id", "") if granted else ""
    if not features and _enterprise_desktop_attendance(request, username):
        features = ["attendance-convert"]
        delivery_id = "attendance-industry"
    return {
        "success": True,
        "custom_features": features,
        "delivery_id": delivery_id,
    }


def require_attendance_conversion(request: Request) -> None:
    if "attendance-convert" not in attendance_custom_features(request)["custom_features"]:
        raise HTTPException(status_code=403, detail="当前账号未开通考勤表转换定制功能")
