"""Create and confirm an order through existing services in one transaction."""

from typing import Any

from app.db.session import get_db


class OrderCreationRejected(ValueError):
    pass


def create_confirmed_order(data: dict[str, Any]) -> dict[str, Any]:
    from app.application.sales_app_service import SalesAppService

    service = SalesAppService()
    try:
        with get_db() as db:
            quoted = service.quote(data, db=db)
            if not quoted.get("success"):
                raise OrderCreationRejected(str(quoted.get("message") or "报价创建失败"))
            confirmed = service.confirm(int(quoted["data"]["id"]), db=db)
            if not confirmed.get("success"):
                raise OrderCreationRejected(str(confirmed.get("message") or "订单确认失败"))
            return {**confirmed, "message": "销售订单已创建并确认"}
    except OrderCreationRejected as exc:
        return {"success": False, "message": str(exc)}
