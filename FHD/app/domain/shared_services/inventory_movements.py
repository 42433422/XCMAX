from __future__ import annotations

import importlib
import logging
import math
from decimal import Decimal
from contextlib import nullcontext
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.business_write_guard import worker_write_guard
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger("app.domain.shared_services.inventory_service")


def _facade():
    return importlib.import_module("app.domain.shared_services.inventory_service")


def _posted_stock_out(db, model, product_id, reference_type, reference_id):
    query = db.query(model).filter(
        model.product_id == product_id,
        model.transaction_type == "out",
        model.reference_type == reference_type,
        model.reference_id == reference_id,
    )
    return query.first()


def _move_available(db: Any, ledger: Any, delta: Decimal, now: datetime) -> bool:
    """Atomic physical/free-stock movement bound to the original tenant and row."""
    model = _facade().InventoryLedger
    physical = Decimal(str(ledger.quantity or 0))
    available = Decimal(str(ledger.available_quantity or 0))
    reserved = Decimal(str(ledger.reserved_quantity or 0))
    if (
        physical < 0 or available < 0 or reserved < 0
        or physical != available + reserved
        or available + delta < 0
    ):
        return False
    changed = db.query(model).filter(
        model.id == ledger.id,
        model.tenant_id == ledger.tenant_id,
        model.quantity == physical,
        model.available_quantity == available,
        model.reserved_quantity == reserved,
    ).update(
        {
            model.quantity: model.quantity + delta,
            model.available_quantity: model.available_quantity + delta,
            model.updated_at: now,
        },
        synchronize_session=False,
    )
    if changed != 1:
        return False
    db.refresh(ledger)
    return True


def _positive_movement_quantity(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("库存变动数量必须是有效正数")
    try:
        quantity = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("库存变动数量必须是有效正数") from exc
    if (
        not math.isfinite(quantity) or quantity <= 0
        or Decimal(str(quantity)).as_tuple().exponent < -4
    ):
        raise ValueError("库存变动数量必须是有效正数")
    return quantity


_DEFAULT_WAREHOUSE_ALIASES = {"default", "default_warehouse", "current_tenant_default", "默认仓库"}


def _positive_id(value: Any) -> int | None:
    if isinstance(value, bool) or value is None or not str(value).strip().isdigit():
        return None
    number = int(str(value).strip())
    return number if number > 0 else None


def _stock_out_warehouse_id(db: Any, warehouse_id: Any) -> tuple[int | None, str, str]:
    """整数仓库编号原样使用；符号/名称只在当前租户内唯一匹配时才解析（#2288）。"""
    numeric = _positive_id(warehouse_id)
    if numeric is not None:
        return numeric, "", ""
    text = str(warehouse_id or "").strip()
    query = db.query(_facade().Warehouse).filter(_facade().Warehouse.status == "active")
    if text.casefold() not in _DEFAULT_WAREHOUSE_ALIASES:
        query = query.filter(_facade().Warehouse.name == text)
    rows = query.limit(2).all() if text else []
    if len(rows) == 1:
        return int(rows[0].id), "", ""
    if not rows and text.casefold() in _DEFAULT_WAREHOUSE_ALIASES:
        return (
            None,
            "当前企业还没有可用仓库：请先在「库存管理」点击「初始化默认仓库」并为产品入库",
            "inventory_warehouse_missing",
        )
    return None, "无法确定出库仓库：请说明从哪个仓库出库", "invalid_warehouse_reference"


class InventoryMovementsMixin:
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def inventory_in(
        self,
        product_id: int | None,
        warehouse_id: int | None,
        quantity: float,
        batch_no: str | None = None,
        location_id: int | None = None,
        unit_price: float | None = None,
        reference_type: str | None = None,
        reference_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
        model_number: str | None = None,
        warehouse_name: str | None = None,
        session: Session | None = None,
    ) -> dict[str, Any]:
        try:
            quantity = _positive_movement_quantity(quantity)
        except ValueError:
            return {"success": False, "message": "入库数量必须是有效正数"}
        with (
            nullcontext(session) if session is not None else _facade().get_db() as db,
            worker_write_guard(db),
        ):
            try:
                if product_id is None and model_number:
                    products = (
                        db.query(_facade().Product)
                        .filter(_facade().Product.model_number == model_number)
                        .limit(2)
                        .all()
                    )
                    if len(products) != 1:
                        return {
                            "success": False,
                            "message": "产品型号不存在或不唯一，请选择明确的产品",
                        }
                    product = products[0]
                else:
                    product = (
                        db.query(_facade().Product)
                        .filter(_facade().Product.id == product_id)
                        .first()
                    )
                if not product:
                    return {"success": False, "message": "产品不存在"}
                if model_number and product.model_number != model_number:
                    return {"success": False, "message": "产品编号与型号不符"}
                if warehouse_id is None and warehouse_name:
                    warehouses = (
                        db.query(_facade().Warehouse)
                        .filter(_facade().Warehouse.name == warehouse_name)
                        .limit(2)
                        .all()
                    )
                    if len(warehouses) != 1:
                        return {
                            "success": False,
                            "message": "仓库名称不存在或不唯一，请选择明确的仓库",
                        }
                    warehouse = warehouses[0]
                else:
                    warehouse = (
                        db.query(_facade().Warehouse)
                        .filter(_facade().Warehouse.id == warehouse_id)
                        .first()
                    )
                if warehouse is None or warehouse.status != "active":
                    return {"success": False, "message": "仓库不存在或未启用"}
                if warehouse_name and warehouse.name != warehouse_name:
                    return {"success": False, "message": "仓库编号与名称不符"}
                product_id, warehouse_id = product.id, warehouse.id
                if location_id is not None:
                    location = db.query(_facade().StorageLocation).filter(
                        _facade().StorageLocation.id == location_id,
                        _facade().StorageLocation.warehouse_id == warehouse_id,
                        _facade().StorageLocation.status == "active",
                    ).first()
                    if location is None:
                        return {"success": False, "message": "入库库位不属于当前仓库或未启用"}
                rows = (
                    db.query(_facade().InventoryLedger)
                    .filter(
                        _facade().InventoryLedger.product_id == product_id,
                        _facade().InventoryLedger.warehouse_id == warehouse_id,
                        _facade().InventoryLedger.batch_no == batch_no,
                        _facade().InventoryLedger.location_id == location_id,
                    )
                    .limit(2)
                    .all()
                )
                if len(rows) > 1:
                    return {
                        "success": False,
                        "error_code": "inventory_identity_ambiguous",
                        "message": "物理库存台账重复，需先核对历史记录",
                    }
                ledger = rows[0] if rows else None
                now = datetime.now()
                if ledger:
                    if not _move_available(db, ledger, Decimal(str(quantity)), now):
                        return {
                            "success": False,
                            "error_code": "inventory_concurrent_change",
                            "message": "入库库存基线已变更或账实不一致，未重复记账",
                        }
                else:
                    ledger = _facade().InventoryLedger(
                        product_id=product_id,
                        warehouse_id=warehouse_id,
                        location_id=location_id,
                        batch_no=batch_no,
                        quantity=quantity,
                        available_quantity=quantity,
                        reserved_quantity=0,
                        unit=product.unit or "个",
                        in_date=now.date(),
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(ledger)
                db.flush()
                transaction = _facade().InventoryTransaction(
                    ledger_id=ledger.id,
                    transaction_type="in",
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    location_id=location_id,
                    batch_no=batch_no,
                    quantity=quantity,
                    before_quantity=float(ledger.quantity) - quantity,
                    after_quantity=float(ledger.quantity),
                    unit_price=unit_price,
                    total_amount=quantity * unit_price if unit_price else None,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    transaction_date=now,
                    operator=operator,
                    remark=remark,
                    created_at=now,
                )
                db.add(transaction)
                if session is None:
                    db.commit()
                return {
                    "success": True,
                    "message": "入库成功",
                    "data": {
                        "ledger_id": ledger.id,
                        "quantity": quantity,
                        "total_quantity": float(ledger.quantity),
                    },
                }
            except RECOVERABLE_ERRORS as e:
                if session is None:
                    db.rollback()
                _facade().logger.error("入库失败: %s", e)
                return {"success": False, "message": str(e)}

    def inventory_out(
        self,
        product_id: int,
        warehouse_id: int,
        quantity: float,
        batch_no: str | None = None,
        location_id: int | None = None,
        reference_type: str | None = None,
        reference_id: int | None = None,
        operator: str | None = None,
        remark: str | None = None,
    ) -> dict[str, Any]:
        try:
            quantity = _positive_movement_quantity(quantity)
        except ValueError:
            return {"success": False, "message": "出库数量必须是有效正数"}
        resolved_product_id = _positive_id(product_id)
        if resolved_product_id is None:
            return {
                "success": False,
                "error_code": "invalid_product_reference",
                "message": "出库产品编号无效：请先查询并确认要出库的具体产品",
            }
        with _facade().get_db() as db, worker_write_guard(db):
            try:
                stock_model = _facade().InventoryTransaction
                resolved_warehouse_id, problem, error_code = _stock_out_warehouse_id(
                    db, warehouse_id
                )
                if resolved_warehouse_id is None:
                    return {"success": False, "error_code": error_code, "message": problem}
                if reference_type and reference_id not in (None, ""):
                    posted = _posted_stock_out(
                        db, stock_model, resolved_product_id, str(reference_type), reference_id
                    )
                    if posted is not None:
                        if (
                            Decimal(str(-posted.quantity)) != Decimal(str(quantity))
                            or posted.warehouse_id != resolved_warehouse_id
                            or posted.batch_no != batch_no
                            or posted.location_id != location_id
                        ):
                            return {
                                "success": False,
                                "error_code": "inventory_replay_conflict",
                                "message": "原出库单据身份已使用，数量或库存归属不一致",
                            }
                        return {
                            "success": True,
                            "message": "该业务单据已出库，未重复扣减",
                            "data": {
                                "already_posted": True,
                                "ledger_id": posted.ledger_id,
                                "quantity": quantity,
                            },
                        }
                query = db.query(_facade().InventoryLedger).filter(
                    _facade().InventoryLedger.product_id == resolved_product_id,
                    _facade().InventoryLedger.warehouse_id == resolved_warehouse_id,
                    _facade().InventoryLedger.available_quantity >= quantity,
                )
                if batch_no:
                    query = query.filter(_facade().InventoryLedger.batch_no == batch_no)
                if location_id:
                    query = query.filter(_facade().InventoryLedger.location_id == location_id)
                rows = query.limit(2).all()
                if len(rows) > 1:
                    return {
                        "success": False,
                        "error_code": "inventory_identity_ambiguous",
                        "message": "多个批次或库位均可出库，请明确原库存归属",
                    }
                ledger = rows[0] if rows else None
                if not ledger:
                    return {
                        "success": False,
                        "error_code": "inventory_insufficient_stock",
                        "message": "库存不足或库存记录不存在",
                    }
                now = datetime.now()
                if not _move_available(db, ledger, -Decimal(str(quantity)), now):
                    return {
                        "success": False,
                        "error_code": "inventory_concurrent_change",
                        "message": "可用库存不足、账实不一致或被并发变更，未扣减",
                    }
                transaction = stock_model(
                    ledger_id=ledger.id,
                    transaction_type="out",
                    document_posting=True,
                    product_id=resolved_product_id,
                    warehouse_id=resolved_warehouse_id,
                    location_id=location_id,
                    batch_no=batch_no,
                    quantity=-quantity,
                    before_quantity=float(ledger.quantity) + quantity,
                    after_quantity=float(ledger.quantity),
                    reference_type=reference_type,
                    reference_id=reference_id,
                    transaction_date=now,
                    operator=operator,
                    remark=remark,
                    created_at=now,
                )
                db.add(transaction)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    raced = _posted_stock_out(
                        db, stock_model, resolved_product_id, str(reference_type), reference_id
                    )
                    if raced is None:
                        raise
                    if (
                        Decimal(str(-raced.quantity)) != Decimal(str(quantity))
                        or raced.warehouse_id != resolved_warehouse_id
                        or raced.batch_no != batch_no
                        or raced.location_id != location_id
                    ):
                        return {
                            "success": False,
                            "error_code": "inventory_replay_conflict",
                            "message": "并发出库身份冲突，原请求的参数不一致",
                        }
                    return {
                        "success": True,
                        "message": "该业务单据已出库，未重复扣减",
                        "data": {
                            "already_posted": True,
                            "ledger_id": raced.ledger_id,
                            "quantity": quantity,
                        },
                    }
                return {
                    "success": True,
                    "message": "出库成功",
                    "data": {
                        "ledger_id": ledger.id,
                        "quantity": quantity,
                        "remaining_quantity": float(ledger.quantity),
                    },
                }
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error("出库失败: %s", e)
                return {"success": False, "message": str(e)}

    def inventory_transfer(
        self,
        product_id: int,
        from_warehouse_id: int,
        to_warehouse_id: int,
        quantity: float,
        from_location_id: int | None = None,
        to_location_id: int | None = None,
        batch_no: str | None = None,
        operator: str | None = None,
        remark: str | None = None,
    ) -> dict[str, Any]:
        try:
            quantity = _positive_movement_quantity(quantity)
        except ValueError:
            return {"success": False, "message": "调拨数量必须是有效正数"}
        if from_warehouse_id == to_warehouse_id:
            return {"success": False, "message": "调拨的源仓库和目标仓库不能相同"}
        with _facade().get_db() as db, worker_write_guard(db):
            try:
                warehouses = db.query(_facade().Warehouse).filter(
                    _facade().Warehouse.id.in_((from_warehouse_id, to_warehouse_id)),
                    _facade().Warehouse.status == "active",
                ).all()
                if {w.id for w in warehouses} != {from_warehouse_id, to_warehouse_id}:
                    return {"success": False, "message": "调拨仓库不存在或未启用"}
                if to_location_id is not None:
                    location = db.query(_facade().StorageLocation).filter(
                        _facade().StorageLocation.id == to_location_id,
                        _facade().StorageLocation.warehouse_id == to_warehouse_id,
                        _facade().StorageLocation.status == "active",
                    ).first()
                    if location is None:
                        return {"success": False, "message": "目标库位不属于目标仓库或未启用"}
                source = db.query(_facade().InventoryLedger).filter(
                    _facade().InventoryLedger.product_id == product_id,
                    _facade().InventoryLedger.warehouse_id == from_warehouse_id,
                    _facade().InventoryLedger.available_quantity >= quantity,
                )
                if batch_no is not None:
                    source = source.filter(_facade().InventoryLedger.batch_no == batch_no)
                if from_location_id is not None:
                    source = source.filter(
                        _facade().InventoryLedger.location_id == from_location_id
                    )
                source_rows = source.limit(2).all()
                if len(source_rows) > 1:
                    return {
                        "success": False,
                        "error_code": "inventory_identity_ambiguous",
                        "message": "调拨来源存在多个批次或库位，请明确选择",
                    }
                from_ledger = source_rows[0] if source_rows else None
                if not from_ledger:
                    return {"success": False, "message": "源仓库库存不足"}
                now = datetime.now()
                if not _move_available(db, from_ledger, -Decimal(str(quantity)), now):
                    return {
                        "success": False,
                        "error_code": "inventory_concurrent_change",
                        "message": "源仓库存已被并发修改或账实不一致，未调拨",
                    }
                out_transaction = _facade().InventoryTransaction(
                    ledger_id=from_ledger.id,
                    transaction_type="transfer_out",
                    product_id=product_id,
                    warehouse_id=from_warehouse_id,
                    location_id=from_ledger.location_id,
                    batch_no=from_ledger.batch_no,
                    quantity=-quantity,
                    before_quantity=float(from_ledger.quantity) + quantity,
                    after_quantity=float(from_ledger.quantity),
                    reference_type="transfer",
                    transaction_date=now,
                    operator=operator,
                    remark=f"调出至仓库{to_warehouse_id}",
                    created_at=now,
                )
                db.add(out_transaction)
                target_rows = (
                    db.query(_facade().InventoryLedger)
                    .filter(
                        _facade().InventoryLedger.product_id == product_id,
                        _facade().InventoryLedger.warehouse_id == to_warehouse_id,
                        _facade().InventoryLedger.batch_no == from_ledger.batch_no,
                        _facade().InventoryLedger.location_id == to_location_id,
                    )
                    .limit(2)
                    .all()
                )
                if len(target_rows) > 1:
                    db.rollback()
                    return {
                        "success": False,
                        "error_code": "inventory_identity_ambiguous",
                        "message": "目标物理库存重复，原调出已回滚",
                    }
                to_ledger = target_rows[0] if target_rows else None
                if to_ledger:
                    if not _move_available(db, to_ledger, Decimal(str(quantity)), now):
                        db.rollback()
                        return {
                            "success": False,
                            "error_code": "inventory_concurrent_change",
                            "message": "目标仓库存已被并发修改或账实不一致，原调出已回滚",
                        }
                else:
                    to_ledger = _facade().InventoryLedger(
                        product_id=product_id,
                        warehouse_id=to_warehouse_id,
                        location_id=to_location_id,
                        batch_no=from_ledger.batch_no,
                        quantity=quantity,
                        available_quantity=quantity,
                        reserved_quantity=0,
                        unit=from_ledger.unit,
                        in_date=now.date(),
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(to_ledger)
                db.flush()
                in_transaction = _facade().InventoryTransaction(
                    ledger_id=to_ledger.id,
                    transaction_type="transfer_in",
                    product_id=product_id,
                    warehouse_id=to_warehouse_id,
                    location_id=to_location_id,
                    batch_no=from_ledger.batch_no,
                    quantity=quantity,
                    before_quantity=float(to_ledger.quantity) - quantity,
                    after_quantity=float(to_ledger.quantity),
                    reference_type="transfer",
                    transaction_date=now,
                    operator=operator,
                    remark=f"从仓库{from_warehouse_id}调入",
                    created_at=now,
                )
                db.add(in_transaction)
                db.commit()
                return {
                    "success": True,
                    "message": "调拨成功",
                    "data": {
                        "from_ledger_id": from_ledger.id,
                        "to_ledger_id": to_ledger.id,
                        "quantity": quantity,
                    },
                }
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error("调拨失败: %s", e)
                return {"success": False, "message": str(e)}
