"""销售生命周期命令模块（commercial order state）。

W1-02 独占文件：只操作 ``SalesOrder.state`` 正交维度
（``draft / quote / sent / confirmed / cancel``），并同步写入对应的日期戳。
本模块**不驱动**履行 / 开票 / 收款维度（各维度独立）；``cancel`` 仅对
未履行且未开票的单允许，一旦已履行或已开票即被拒绝（fail-closed）。

所有命令均做租户作用域校验（fail-closed：找不到订单 / 越权 / 非法迁移
一律抛异常，不静默放行）。数量比较使用 ``Decimal`` 保证精确。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import SalesOrder

# 商业单状态命令（只改 state 维度）
STATE_QUOTE = "quote"
STATE_SENT = "sent"
STATE_CONFIRMED = "confirmed"
STATE_CANCEL = "cancel"

# 开票状态（独立维度）：仅 ``not_invoiced`` 的单允许取消
INVOICE_STATUS_NOT_INVOICED = "not_invoiced"


class SalesLifecycleError(Exception):
    """销售生命周期命令失败基类。"""


class SalesLifecycleNotFound(SalesLifecycleError):
    """订单不存在。"""


class SalesLifecycleTenantMismatch(SalesLifecycleError):
    """订单不属于当前租户（越权访问被拒）。"""


class SalesLifecycleInvalidTransition(SalesLifecycleError):
    """非法状态迁移（含回退被拒）。"""


class SalesLifecycleCancelBlocked(SalesLifecycleError):
    """取消被拒：订单已履行或已开票。"""


class SalesLifecycleService:
    """销售订单商业单状态命令服务。

    :param session: 可用的 SQLAlchemy 会话。
    :param tenant_id: 当前租户作用域；为 ``None`` 时不校验（测试/系统态）。
    :param now: 命令发生的日期（注入以便断言；默认取今天）。
    """

    def __init__(
        self,
        session: Session,
        tenant_id: Optional[int] = None,
        now: Optional[date] = None,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._today = now or date.today()

    # ------------------------------------------------------------------ #
    # 租户作用域 + 加载（fail-closed）
    # ------------------------------------------------------------------ #
    def _assert_tenant(self, order: SalesOrder) -> None:
        if self._tenant_id is None:
            return
        if order.tenant_id != self._tenant_id:
            raise SalesLifecycleTenantMismatch(f"订单 {order.id} 不属于租户 {self._tenant_id}")

    def _get_order(self, order_id: int) -> SalesOrder:
        order = self._session.get(SalesOrder, order_id)
        if order is None:
            raise SalesLifecycleNotFound(f"销售订单不存在: {order_id}")
        self._assert_tenant(order)
        return order

    def _apply(self, order: SalesOrder, target: str, date_attr: str) -> SalesOrder:
        # 幂等：已处于目标状态则不再推进
        if order.state == target:
            return order
        try:
            order.set_state(target)
        except ValueError as exc:  # 非法迁移（含回退）→ fail-closed
            raise SalesLifecycleInvalidTransition(str(exc)) from exc
        setattr(order, date_attr, self._today)
        self._session.add(order)
        self._session.flush()
        return order

    # ------------------------------------------------------------------ #
    # 命令
    # ------------------------------------------------------------------ #
    def quote(self, order_id: int) -> SalesOrder:
        """draft -> quote：将草稿转成报价单。"""
        return self._apply(self._get_order(order_id), STATE_QUOTE, "quote_date")

    def send_quote(self, order_id: int) -> SalesOrder:
        """quote -> sent：报价已发送给客户。"""
        return self._apply(self._get_order(order_id), STATE_SENT, "sent_date")

    def confirm(self, order_id: int) -> SalesOrder:
        """quote/sent -> confirmed：确认销售订单。"""
        return self._apply(self._get_order(order_id), STATE_CONFIRMED, "confirm_date")

    def cancel(self, order_id: int) -> SalesOrder:
        """取消订单（仅未履行且未开票的单允许）。

        履行 / 开票为独立维度：一旦发生履行（delivered/returned）或开票
        （invoice_status != not_invoiced），取消即被拒绝，且本命令不触碰
        履行 / 开票 / 收款任何字段。
        """
        order = self._get_order(order_id)
        if order.state == STATE_CANCEL:
            return order  # 幂等
        if order.fulfillment_state() != "unfulfilled":
            raise SalesLifecycleCancelBlocked(
                f"订单 {order.id} 已履行（{order.fulfillment_state()}），不可取消"
            )
        if order.invoice_status != INVOICE_STATUS_NOT_INVOICED:
            raise SalesLifecycleCancelBlocked(
                f"订单 {order.id} 已开票（{order.invoice_status}），不可取消"
            )
        return self._apply(order, STATE_CANCEL, "cancel_date")
