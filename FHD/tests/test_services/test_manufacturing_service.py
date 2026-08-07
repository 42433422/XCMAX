"""
MRP 生产制造服务单元测试（Task 3：upgrade-erp-modules-odoo18）

覆盖 "建 BOM → 下达 → 领料原料-N → 完工成品+M" 全链路，
使用真实 sqlite :memory: 并通过 patch 让两个服务复用同一测试库。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.inventory_service as inv_svc_mod
import app.services.manufacturing_service as mrp_svc_mod
from app.db.base import Base
from app.db.models.inventory import InventoryLedger, Warehouse
from app.db.models.mrp import Bom, BomLine, ManufacturingOrder, ManufacturingOrderLine
from app.db.models.product import Product
from app.services.manufacturing_service import ManufacturingService


@pytest.fixture(scope="function")
def mrp_env():
    """真实 sqlite :memory: 库 + 把两个服务模块的 get_db 指向同一测试库。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    @contextmanager
    def test_db():
        db = session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    with (
        patch.object(mrp_svc_mod, "get_db", test_db),
        patch.object(inv_svc_mod, "get_db", test_db),
    ):
        with test_db() as db:
            finish_product = Product(model_number="FG-001", name="成品A", unit="个")
            raw1 = Product(model_number="RM-001", name="原料X", unit="个")
            raw2 = Product(model_number="RM-002", name="原料Y", unit="个")
            db.add_all([finish_product, raw1, raw2])
            db.flush()

            wh = Warehouse(code="WH01", name="主仓库", status="active")
            db.add(wh)
            db.flush()

            now = datetime.now()
            db.add_all(
                [
                    InventoryLedger(
                        product_id=raw1.id,
                        warehouse_id=wh.id,
                        quantity=100,
                        available_quantity=100,
                        reserved_quantity=0,
                        unit="个",
                        in_date=now.date(),
                        created_at=now,
                        updated_at=now,
                    ),
                    InventoryLedger(
                        product_id=raw2.id,
                        warehouse_id=wh.id,
                        quantity=50,
                        available_quantity=50,
                        reserved_quantity=0,
                        unit="个",
                        in_date=now.date(),
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            db.commit()

            env = {
                "finish_product_id": finish_product.id,
                "raw1_id": raw1.id,
                "raw2_id": raw2.id,
                "warehouse_id": wh.id,
            }
        yield env


class TestManufacturingFullChain:
    def test_full_chain(self, mrp_env):
        """建 BOM → 下达 → 领料原料-N → 完工成品+M 全链路。"""
        svc = ManufacturingService()
        env = mrp_env

        # 1. 建 BOM：成品A 由 2个原料X + 1个原料Y 构成
        bom_result = svc.create_bom(
            {
                "code": "BOM-FG-001",
                "product_id": env["finish_product_id"],
                "product_name": "成品A",
                "quantity": 1,
                "status": "active",
                "lines": [
                    {
                        "product_id": env["raw1_id"],
                        "product_name": "原料X",
                        "quantity": 2,
                        "unit": "个",
                    },
                    {
                        "product_id": env["raw2_id"],
                        "product_name": "原料Y",
                        "quantity": 1,
                        "unit": "个",
                    },
                ],
            }
        )
        assert bom_result["success"] is True
        bom_id = bom_result["data"]["id"]
        assert len(bom_result["data"]["lines"]) == 2

        # 2. 下达生产 10 个成品
        order_result = svc.create_order(
            {
                "bom_id": bom_id,
                "quantity": 10,
                "warehouse_id": env["warehouse_id"],
                "order_no": "MO-2026-0001",
            }
        )
        assert order_result["success"] is True
        order_id = order_result["data"]["id"]
        plan_lines = {
            line["product_id"]: line["quantity"] for line in order_result["data"]["lines"]
        }
        # 计划领料量 = BOM 单耗 * 工单数量
        assert plan_lines[env["raw1_id"]] == 20  # 2 * 10
        assert plan_lines[env["raw2_id"]] == 10  # 1 * 10

        # 未下达前不可领料
        consume_fail = svc.consume(
            order_id, env["warehouse_id"], operator="测试员"
        )
        assert consume_fail["success"] is False

        # 3. 下达
        confirm = svc.confirm_order(order_id)
        assert confirm["success"] is True
        assert confirm["data"]["status"] == "confirmed"

        # 4. 领料：扣减原料
        consume = svc.consume(order_id, env["warehouse_id"], operator="测试员")
        assert consume["success"] is True
        assert consume["data"]["status"] == "in_progress"
        for line in consume["data"]["lines"]:
            assert line["consumed_quantity"] == line["quantity"]

        # 5. 完工：成品入库
        finish = svc.finish(order_id, env["warehouse_id"], operator="测试员")
        assert finish["success"] is True
        assert finish["data"]["status"] == "done"
        assert finish["inbound"]["quantity"] == 10

        # 6. 校验库存：成品 +10，原料已扣减
        # 直接查询测试库（get_db 已被 fixture patch 到同一库）校验库存
        with inv_svc_mod.get_db() as db:
            fg_ledger = (
                db.query(InventoryLedger)
                .filter(
                    InventoryLedger.product_id == env["finish_product_id"],
                    InventoryLedger.warehouse_id == env["warehouse_id"],
                )
                .first()
            )
            assert fg_ledger is not None
            assert float(fg_ledger.available_quantity) == 10

            raw1_ledger = (
                db.query(InventoryLedger)
                .filter(
                    InventoryLedger.product_id == env["raw1_id"],
                    InventoryLedger.warehouse_id == env["warehouse_id"],
                )
                .first()
            )
            assert float(raw1_ledger.available_quantity) == 80  # 100 - 20

            raw2_ledger = (
                db.query(InventoryLedger)
                .filter(
                    InventoryLedger.product_id == env["raw2_id"],
                    InventoryLedger.warehouse_id == env["warehouse_id"],
                )
                .first()
            )
            assert float(raw2_ledger.available_quantity) == 40  # 50 - 10

    def test_consume_insufficient_stock(self, mrp_env):
        """领料时原料库存不足应失败。"""
        svc = ManufacturingService()
        env = mrp_env
        bom_result = svc.create_bom(
            {
                "code": "BOM-FG-002",
                "product_id": env["finish_product_id"],
                "product_name": "成品A",
                "quantity": 1,
                "status": "active",
                "lines": [
                    {
                        "product_id": env["raw1_id"],
                        "product_name": "原料X",
                        "quantity": 2,
                        "unit": "个",
                    }
                ],
            }
        )
        bom_id = bom_result["data"]["id"]
        order_result = svc.create_order(
            {"bom_id": bom_id, "quantity": 100, "warehouse_id": env["warehouse_id"]}
        )
        order_id = order_result["data"]["id"]
        svc.confirm_order(order_id)  # 需 200 原料X，但仅有 100

        result = svc.consume(order_id, env["warehouse_id"], operator="测试员")
        assert result["success"] is False
        assert "库存不足" in result["message"]

    def test_query_boms_and_orders(self, mrp_env):
        """查询 BOM 与工单列表。"""
        svc = ManufacturingService()
        env = mrp_env
        svc.create_bom(
            {
                "code": "BOM-Q1",
                "product_id": env["finish_product_id"],
                "product_name": "成品A",
                "quantity": 1,
                "status": "active",
                "lines": [
                    {
                        "product_id": env["raw1_id"],
                        "product_name": "原料X",
                        "quantity": 1,
                        "unit": "个",
                    }
                ],
            }
        )
        boms = svc.query_boms()
        assert boms["success"] is True
        assert boms["total"] == 1

        get_bom = svc.get_bom(boms["data"][0]["id"])
        assert get_bom["success"] is True
        assert svc.get_bom(999999)["success"] is False

        orders = svc.query_orders()
        assert orders["success"] is True
        assert orders["total"] == 0