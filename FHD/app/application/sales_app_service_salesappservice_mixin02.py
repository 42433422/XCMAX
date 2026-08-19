# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.sales_app_service')

class _SalesAppServicePart02Mixin:

    def _closed_loop_persist_fingerprint(self, db, order_id: int, fingerprint: str) -> None:
        """在同一外层事务内把复合指纹命名空间化写入既有 remark 字段。

        保留既有顶层 ``idempotency:sales_quote:{key}`` 标记不动，仅追加指纹标记，
        使 quote() 的幂等查询（前缀匹配）与复合重放校验都能兼容工作。
        """
        order_obj = db.query(_facade().SalesOrder).filter(_facade().SalesOrder.id == order_id).first()
        if order_obj is None:
            raise _facade().ClosedLoopExecutionError('idempotency', '幂等订单写入失败')
        fp_marker = f'{_facade()._CLOSED_LOOP_FP_PREFIX}:{fingerprint}'
        base = order_obj.remark or ''
        if fp_marker in base:
            return
        order_obj.remark = f'{base}\n{fp_marker}' if base else fp_marker

    def _closed_loop_resolve_customer(self, db, order: dict[str, _facade().Any], tenant_id: int) -> dict[str, _facade().Any]:
        cid = order.get('customer_id')
        if cid is not None:
            cid_int = self._closed_loop_coerce_id(cid, 'resolve_customer', 'customer_id')
            customer = db.query(_facade().Customer).filter(_facade().Customer.id == cid_int, _facade().Customer.tenant_id == tenant_id).first()
            if customer is None:
                raise _facade().ClosedLoopExecutionError('resolve_customer', f'当前租户下客户不存在: id={cid}')
            return {'id': customer.id, 'name': customer.customer_name}
        cname = order.get('customer_name')
        resolution = order.get('customer_resolution')
        if resolution != 'current_tenant_exact_name':
            raise _facade().ClosedLoopExecutionError('resolve_customer', f'不支持的客户解析方式: {resolution}')
        matches = db.query(_facade().Customer).filter(_facade().Customer.customer_name == cname, _facade().Customer.tenant_id == tenant_id).count()
        if matches == 1:
            customer = db.query(_facade().Customer).filter(_facade().Customer.customer_name == cname, _facade().Customer.tenant_id == tenant_id).first()
            return {'id': customer.id, 'name': customer.customer_name}
        if matches != 0:
            raise _facade().ClosedLoopExecutionError('resolve_customer', f'客户名匹配数为 {matches}（应为恰好 1）: {cname}')
        from app.db.models.purchase_unit import PurchaseUnit
        purchase_units = db.query(PurchaseUnit).filter(PurchaseUnit.unit_name == cname, PurchaseUnit.tenant_id == tenant_id).limit(2).all()
        if len(purchase_units) != 1:
            raise _facade().ClosedLoopExecutionError('resolve_customer', f'采购单位匹配数为 {len(purchase_units)}（应为恰好 1）: {cname}')
        purchase_unit = purchase_units[0]
        customer = _facade().Customer(customer_name=purchase_unit.unit_name, contact_person=purchase_unit.contact_person, contact_phone=purchase_unit.contact_phone, contact_address=purchase_unit.address, tenant_id=tenant_id)
        db.add(customer)
        db.flush()
        return {'id': customer.id, 'name': customer.customer_name}

    def _closed_loop_resolve_products(self, db, order: dict[str, _facade().Any], tenant_id: int) -> list[dict[str, _facade().Any]]:
        resolved = []
        for (idx, item) in enumerate(order['items']):
            pid = item.get('product_id')
            if pid is not None:
                pid_int = self._closed_loop_coerce_id(pid, 'resolve_product', 'product_id')
                product = db.query(_facade().Product).filter(_facade().Product.id == pid_int, _facade().Product.tenant_id == tenant_id).first()
                if product is None:
                    raise _facade().ClosedLoopExecutionError('resolve_product', f'当前租户下产品不存在: id={pid}')
            else:
                pname = item.get('product_name')
                resolution = item.get('product_resolution')
                if resolution != 'current_tenant_exact_name':
                    raise _facade().ClosedLoopExecutionError('resolve_product', f'不支持的产品解析方式: {resolution}')
                matches = db.query(_facade().Product).filter(_facade().Product.name == pname, _facade().Product.tenant_id == tenant_id).count()
                if matches != 1:
                    raise _facade().ClosedLoopExecutionError('resolve_product', f'产品名匹配数为 {matches}（应为恰好 1）: {pname}')
                product = db.query(_facade().Product).filter(_facade().Product.name == pname, _facade().Product.tenant_id == tenant_id).first()
            unit = item.get('unit')
            if product.unit and product.unit != unit:
                raise _facade().ClosedLoopExecutionError('resolve_product', f'产品单位不匹配: 产品={product.unit} vs 载荷={unit}')
            resolved.append({'product_id': product.id, 'unit': unit, 'quantity': _facade().Decimal(str(item['quantity'])), 'unit_price': _facade().Decimal(str(item['unit_price'])), 'product_name': product.name})
        return resolved

    def _closed_loop_resolve_warehouse(self, db, fulfillment: dict[str, _facade().Any], tenant_id: int) -> dict[str, _facade().Any]:
        wid = fulfillment.get('warehouse_id')
        if wid is not None:
            wid_int = self._closed_loop_coerce_id(wid, 'resolve_warehouse', 'warehouse_id')
            wh = db.query(_facade().Warehouse).filter(_facade().Warehouse.id == wid_int, _facade().Warehouse.tenant_id == tenant_id).first()
            if wh is None:
                raise _facade().ClosedLoopExecutionError('resolve_warehouse', f'当前租户下仓库不存在: id={wid}')
            return {'id': wh.id, 'code': wh.code}
        resolution = fulfillment.get('warehouse_resolution')
        if resolution != 'current_tenant_default':
            raise _facade().ClosedLoopExecutionError('resolve_warehouse', f'不支持的仓库解析方式: {resolution}')
        wh = db.query(_facade().Warehouse).filter(_facade().Warehouse.status == 'active', _facade().Warehouse.tenant_id == tenant_id).order_by(_facade().Warehouse.id.asc()).first()
        if wh is None:
            raise _facade().ClosedLoopExecutionError('resolve_warehouse', '当前租户下无可用仓库')
        return {'id': wh.id, 'code': wh.code}

    def _closed_loop_resolve_inventory_source(self, db, *, product_id: int, warehouse_id: int, quantity: _facade().Decimal, tenant_id: int) -> dict[str, _facade().Any]:
        """解析闭环交付使用的唯一库存批次，避免把有批次库存误判为不存在。

        桌面正常入库允许填写批次号，而库存扣减服务按 ``batch_no`` 精确匹配。
        闭环载荷未显式指定批次时，只接受当前租户、产品、仓库下恰好一个库存充足
        的台账；缺失或多个候选均 fail-closed，绝不静默挑选错误批次。
        """
        ledgers = db.query(_facade().InventoryLedger).filter(_facade().InventoryLedger.product_id == product_id, _facade().InventoryLedger.warehouse_id == warehouse_id, _facade().InventoryLedger.tenant_id == tenant_id, _facade().InventoryLedger.available_quantity >= quantity).order_by(_facade().InventoryLedger.id.asc()).limit(2).all()
        if len(ledgers) != 1:
            raise _facade().ClosedLoopExecutionError('resolve_inventory', f'可交付库存台账匹配数为 {len(ledgers)}（应为恰好 1）')
        ledger = ledgers[0]
        return {'batch_no': ledger.batch_no, 'location_id': ledger.location_id}

    @staticmethod
    def _generate_order_no() -> str:
        return f"SO{_facade().datetime.now().strftime('%Y%m%d%H%M%S')}"
