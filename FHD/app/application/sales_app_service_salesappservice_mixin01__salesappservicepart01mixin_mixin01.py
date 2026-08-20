# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.sales_app_service")


class __SalesAppServicePart01MixinPart01Mixin:
    def query(
        self,
        status: str | None = None,
        customer_id: int | None = None,
        customer_name: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, _facade().Any]:
        """按状态/客户/关键字查询销售订单列表。"""
        with _facade().get_db() as db:
            q = db.query(_facade().SalesOrder)
            if status:
                q = q.filter(_facade().SalesOrder.status == status)
            if customer_id:
                q = q.filter(_facade().SalesOrder.customer_id == customer_id)
            if customer_name:
                q = q.filter(_facade().SalesOrder.customer_name == customer_name)
            if keyword:
                like = f"%{keyword}%"
                q = q.filter(
                    _facade().SalesOrder.order_no.like(like)
                    | _facade().SalesOrder.customer_name.like(like)
                )
            total = q.count()
            orders = (
                q.order_by(_facade().SalesOrder.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )
            return {
                "success": True,
                "data": [o.to_dict() for o in orders],
                "total": total,
                "page": page,
                "per_page": per_page,
            }

    def quote(
        self, data: dict[str, _facade().Any], *, db: _facade().Any = None
    ) -> dict[str, _facade().Any]:
        """创建报价单（state=quote），明细项由 items 提供。

        可选 ``idempotency_key``：同 key 重复调用不重复建单（端到端幂等，GAP-3）。
        可选 ``db``：调用方持有的 SQLAlchemy 会话。提供时使用该精确对象并交由调用方
        负责提交/回滚（本方法仅 flush/refresh，不 commit/rollback/close）；缺省时沿用
        本模块 ``get_db()`` 自有会话并自行提交。
        """
        customer_id = data.get("customer_id")
        items_data = data.get("items") or []
        if not customer_id:
            return {"success": False, "message": "缺少 customer_id"}
        if not isinstance(items_data, list) or not items_data:
            return {"success": False, "message": "缺少 items 明细"}
        idempotency_key = str(data.get("idempotency_key") or "").strip() or None
        idem_marker = f"idempotency:sales_quote:{idempotency_key}" if idempotency_key else None
        owned = db is None
        cm = _facade().nullcontext(db) if not owned else _facade().get_db()
        with cm as ctx:
            if idem_marker:
                existing = (
                    ctx.query(_facade().SalesOrder)
                    .filter(
                        _facade().or_(
                            _facade().SalesOrder.remark == idem_marker,
                            _facade().SalesOrder.remark.startswith(
                                idem_marker + "\n" + _facade()._CLOSED_LOOP_FP_PREFIX + ":",
                                autoescape=True,
                                escape="\\",
                            ),
                        )
                    )
                    .order_by(_facade().SalesOrder.id.desc())
                    .first()
                )
                if existing is not None:
                    return {
                        "success": True,
                        "message": f"报价单已存在（幂等）: {existing.order_no}",
                        "data": existing.to_dict(),
                        "idempotent": True,
                    }
            customer = (
                ctx.query(_facade().Customer)
                .filter(_facade().Customer.id == int(customer_id))
                .first()
            )
            if customer is None:
                return {"success": False, "message": f"客户不存在: customer_id={customer_id}"}
            total_amount = _facade().Decimal("0")
            order_no = data.get("order_no") or self._generate_order_no()
            order = _facade().SalesOrder(
                order_no=order_no,
                customer_id=customer.id,
                customer_name=customer.customer_name,
                state="quote",
                status="quote",
                quote_date=data.get("quote_date", _facade().datetime.now().date()),
                total_amount=_facade().Decimal("0"),
                paid_amount=_facade().Decimal("0"),
                currency=data.get("currency", "CNY"),
                remark=idem_marker or data.get("remark"),
                created_at=_facade().datetime.now(),
            )
            ctx.add(order)
            ctx.flush()
            for item_data in items_data:
                product_id = item_data.get("product_id")
                product = (
                    ctx.query(_facade().Product).filter(_facade().Product.id == product_id).first()
                    if product_id
                    else None
                )
                quantity = _facade()._to_decimal(item_data.get("quantity", "0"))
                unit_price = _facade()._to_decimal(item_data.get("unit_price", "0"))
                amount = quantity * unit_price
                total_amount += amount
                ctx.add(
                    _facade().SalesOrderItem(
                        order_id=order.id,
                        product_id=product_id,
                        product_name=product.name if product else item_data.get("product_name"),
                        specification=item_data.get("specification"),
                        quantity=quantity,
                        unit=item_data.get("unit", "个"),
                        unit_price=unit_price,
                        amount=amount,
                        ordered_quantity=quantity,
                        delivered_quantity=_facade().Decimal("0"),
                        returned_quantity=_facade().Decimal("0"),
                        invoiced_quantity=_facade().Decimal("0"),
                        status="pending",
                        remark=item_data.get("remark"),
                        created_at=_facade().datetime.now(),
                    )
                )
            order.total_amount = total_amount
            ctx.flush()
            if owned:
                ctx.commit()
            ctx.refresh(order)
            return {
                "success": True,
                "message": f"报价单已创建: {order.order_no}",
                "data": order.to_dict(),
            }

    @staticmethod
    def _lifecycle_service(db: _facade().Any) -> _facade().SalesLifecycleService:
        """构造生命周期服务：绑定当前会话与租户作用域。"""
        return _facade().SalesLifecycleService(db, tenant_id=_facade().current_tenant_id())

    @staticmethod
    def _order_result(order: _facade().SalesOrder) -> dict[str, _facade().Any]:
        return {
            "success": True,
            "message": f"销售订单 {order.order_no} 已推进至 {order.state}",
            "data": order.to_dict(),
        }

    def confirm(self, order_id: int, *, db: _facade().Any = None) -> dict[str, _facade().Any]:
        """确认销售订单 → 委托 SalesLifecycleService.confirm。

        可选 ``db``：调用方持有的会话，提供时构造 ``SalesLifecycleService`` 绑定该
        精确对象且不打开 ``get_db()``，也绝不 commit/rollback/close；缺省时自开会话。
        """
        owned = db is None
        cm = _facade().nullcontext(db) if not owned else _facade().get_db()
        with cm as ctx:
            try:
                order = self._lifecycle_service(ctx).confirm(int(order_id))
            except _facade().SalesLifecycleError as exc:
                return {"success": False, "message": str(exc)}
            ctx.refresh(order)
            return self._order_result(order)

    def cancel(self, order_id: int) -> dict[str, _facade().Any]:
        """取消订单 → 委托 SalesLifecycleService.cancel。"""
        with _facade().get_db() as db:
            try:
                order = self._lifecycle_service(db).cancel(int(order_id))
            except _facade().SalesLifecycleError as exc:
                return {"success": False, "message": str(exc)}
            db.refresh(order)
            return self._order_result(order)

    def deliver(
        self,
        order_id: int,
        item_id: int,
        quantity: _facade().Decimal | float,
        *,
        warehouse_id: int,
        product_id: int | None = None,
        batch_no: str | None = None,
        location_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
        idempotency_key: str | None = None,
        db: _facade().Any = None,
    ) -> dict[str, _facade().Any]:
        """交付（partial/backorder）→ 委托 FulfillmentService.deliver。

        可选 ``db``：调用方持有的会话，提供时作为 ``db=db`` 恰好透传一次给
        ``FulfillmentService.deliver``；缺省时由履行服务自开会话。
        """
        return (
            _facade()
            .FulfillmentService()
            .deliver(
                order_id,
                item_id,
                float(quantity),
                warehouse_id=warehouse_id,
                product_id=product_id,
                batch_no=batch_no,
                location_id=location_id,
                operator=operator,
                remark=remark,
                idempotency_key=idempotency_key,
                db=db,
            )
        )

    def invoice(
        self,
        order_id: int,
        *,
        partner_id: int | None = None,
        partner_name: str | None = None,
        amount: float | _facade().Decimal | None = None,
        journal_date: _facade().Any = None,
        description: str | None = None,
        db: _facade().Any = None,
    ) -> dict[str, _facade().Any]:
        """开票 → 委托 invoicing_service.invoice。

        可选 ``db``：调用方持有的会话，提供时作为 ``db=db`` 恰好透传一次。
        """
        return _facade().invoice(
            order_id,
            partner_id=partner_id,
            partner_name=partner_name,
            amount=amount,
            journal_date=journal_date,
            description=description,
            db=db,
        )

    def credit_note(
        self, order_id: int, *, journal_date: _facade().Any = None, description: str | None = None
    ) -> dict[str, _facade().Any]:
        """贷项通知单 → 委托 invoicing_service.credit_note。"""
        return _facade().credit_note(order_id, journal_date=journal_date, description=description)

    def payment(
        self,
        order_id: int,
        amount: _facade().Any = None,
        *,
        partner_id: int | None = None,
        partner_name: str | None = None,
        reference: str | None = None,
        journal_date: _facade().Any = None,
        db: _facade().Any = None,
    ) -> dict[str, _facade().Any]:
        """登记收款 → 委托 payment_service.payment。

        可选 ``db``：调用方持有的会话，提供时作为 ``db=db`` 恰好透传一次。
        """
        return _facade().payment(
            sales_order_id=order_id,
            amount=amount,
            partner_id=partner_id,
            partner_name=partner_name,
            reference=reference,
            journal_date=journal_date,
            db=db,
        )

    def refund(
        self,
        allocation_id: int,
        *,
        reference: str | None = None,
        journal_date: _facade().Any = None,
    ) -> dict[str, _facade().Any]:
        """收款退款/冲销 → 委托 payment_service.refund。"""
        return _facade().refund(
            allocation_id=allocation_id, reference=reference, journal_date=journal_date
        )

    def execute_closed_loop(self, payload: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        """销售到收款闭环的真实原子执行器（fail-closed）。

        只在一个外层 ``with get_db()`` 事务内调用 quote/confirm/deliver/invoice/
        payment 等专属拥有方服务，任一失败即整体回滚。任何校验失败或缺少租户
        上下文都返回结构化失败并写入零行，绝不返回被弃用的 NOT_READY 哨兵。
        """
        struct_err = self._closed_loop_validate_structure(payload)
        if struct_err:
            return struct_err
        idempotency_key = payload["idempotency_key"].strip()
        try:
            tenant_id = _facade().tenant_id_for_write()
        except _facade().TenantScopeError:
            return {
                "success": False,
                "error_code": "NO_TENANT_CONTEXT",
                "message": "缺少当前租户上下文，拒绝执行（零持久化）",
                "failed_step": "tenant",
            }
        reject_err = self._closed_loop_reject_tenant_id(payload)
        if reject_err:
            return reject_err
        arith_err = self._closed_loop_validate_arithmetic(payload)
        if arith_err:
            return arith_err
        try:
            with _facade().get_db() as db:
                result = self._closed_loop_run(db, payload, tenant_id, idempotency_key)
            return result
        except _facade().ClosedLoopExecutionError as exc:
            return {
                "success": False,
                "error_code": "CLOSED_LOOP_EXECUTION_FAILED",
                "failed_step": exc.step,
                "message": exc.message,
            }

    @staticmethod
    def _closed_loop_validate_structure(payload: _facade().Any) -> dict[str, _facade().Any] | None:
        if not isinstance(payload, dict) or not payload:
            return {
                "success": False,
                "error_code": "INVALID_CLOSED_LOOP_PAYLOAD",
                "message": "缺少闭合载荷 payload",
            }
        idempotency_key = payload.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            return {
                "success": False,
                "error_code": "INVALID_CLOSED_LOOP_PAYLOAD",
                "message": "闭合载荷缺少非空 idempotency_key",
            }
        for section in ("order", "fulfillment", "invoice", "payment_allocation"):
            sec = payload.get(section)
            if not isinstance(sec, dict) or not sec:
                return {
                    "success": False,
                    "error_code": "INVALID_CLOSED_LOOP_PAYLOAD",
                    "message": f"闭合载荷缺少 dict 区块: {section}",
                }
        return None
