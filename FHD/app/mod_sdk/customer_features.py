"""共享运行模块内的客户定制功能授权；以有效请求会话为边界。"""

from fastapi import HTTPException, Request

from app.enterprise.private_delivery_binding import load_session_private_delivery_binding
from app.infrastructure.auth.dependencies import get_logged_in_user, session_id_from_request
from app.mod_sdk.customer_delivery import delivery_for_account


def attendance_custom_features(request: Request) -> dict:
    get_logged_in_user(request)
    binding = load_session_private_delivery_binding(session_id_from_request(request))
    delivery = delivery_for_account(binding.get("username", "")) or {}
    granted = (
        binding.get("market_user_id")
        and delivery.get("delivery_mode") == "integrated_feature"
        and delivery.get("runtime_mod_id") == "attendance-industry"
        and delivery.get("legacy_mod_id") in binding.get("mod_ids", set())
    )
    return {
        "success": True,
        "custom_features": list(delivery.get("custom_features") or []) if granted else [],
        "delivery_id": delivery.get("legacy_mod_id", "") if granted else "",
    }


def require_attendance_conversion(request: Request) -> None:
    if "attendance-convert" not in attendance_custom_features(request)["custom_features"]:
        raise HTTPException(status_code=403, detail="当前账号未开通考勤表转换定制功能")
