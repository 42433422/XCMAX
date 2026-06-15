"""测试 miniprogram ORM 模型。"""

from __future__ import annotations

import pytest

from app.db.models.miniprogram import (
    MpAddress,
    MpBrowseHistory,
    MpCart,
    MpFavorite,
    MpFeedback,
    MpNotification,
    MpOrder,
    MpOrderItem,
)


class TestMpCart:
    """测试 MpCart 模型。"""

    def test_tablename(self):
        assert MpCart.__tablename__ == "mp_carts"

    def test_has_required_columns(self):
        columns = {c.name for c in MpCart.__table__.columns}
        assert "id" in columns
        assert "user_id" in columns
        assert "product_id" in columns
        assert "quantity" in columns
        assert "selected" in columns

    def test_unique_constraint(self):
        constraints = MpCart.__table_args__
        assert len(constraints) > 0


class TestMpOrder:
    """测试 MpOrder 模型。"""

    def test_tablename(self):
        assert MpOrder.__tablename__ == "mp_orders"

    def test_has_required_columns(self):
        columns = {c.name for c in MpOrder.__table__.columns}
        assert "id" in columns
        assert "order_no" in columns
        assert "user_id" in columns
        assert "status" in columns
        assert "total_amount" in columns

    def test_delivery_fields(self):
        columns = {c.name for c in MpOrder.__table__.columns}
        assert "delivery_name" in columns
        assert "delivery_phone" in columns
        assert "delivery_address" in columns
        assert "delivery_province" in columns
        assert "delivery_city" in columns
        assert "delivery_district" in columns

    def test_payment_fields(self):
        columns = {c.name for c in MpOrder.__table__.columns}
        assert "pay_amount" in columns
        assert "pay_status" in columns
        assert "pay_time" in columns


class TestMpOrderItem:
    """测试 MpOrderItem 模型。"""

    def test_tablename(self):
        assert MpOrderItem.__tablename__ == "mp_order_items"

    def test_has_required_columns(self):
        columns = {c.name for c in MpOrderItem.__table__.columns}
        assert "id" in columns
        assert "order_id" in columns
        assert "product_id" in columns
        assert "product_name" in columns
        assert "quantity" in columns
        assert "unit_price" in columns
        assert "subtotal" in columns


class TestMpAddress:
    """测试 MpAddress 模型。"""

    def test_tablename(self):
        assert MpAddress.__tablename__ == "mp_addresses"

    def test_has_required_columns(self):
        columns = {c.name for c in MpAddress.__table__.columns}
        assert "id" in columns
        assert "user_id" in columns
        assert "contact_name" in columns
        assert "contact_phone" in columns
        assert "province" in columns
        assert "city" in columns
        assert "district" in columns
        assert "detail_address" in columns
        assert "is_default" in columns


class TestMpBrowseHistory:
    """测试 MpBrowseHistory 模型。"""

    def test_tablename(self):
        assert MpBrowseHistory.__tablename__ == "mp_browse_history"

    def test_has_required_columns(self):
        columns = {c.name for c in MpBrowseHistory.__table__.columns}
        assert "id" in columns
        assert "user_id" in columns
        assert "product_id" in columns
        assert "viewed_at" in columns


class TestMpFavorite:
    """测试 MpFavorite 模型。"""

    def test_tablename(self):
        assert MpFavorite.__tablename__ == "mp_favorites"

    def test_has_required_columns(self):
        columns = {c.name for c in MpFavorite.__table__.columns}
        assert "id" in columns
        assert "user_id" in columns
        assert "product_id" in columns


class TestMpNotification:
    """测试 MpNotification 模型。"""

    def test_tablename(self):
        assert MpNotification.__tablename__ == "mp_notifications"

    def test_has_required_columns(self):
        columns = {c.name for c in MpNotification.__table__.columns}
        assert "id" in columns
        assert "user_id" in columns
        assert "title" in columns
        assert "content" in columns
        assert "type" in columns
        assert "is_read" in columns


class TestMpFeedback:
    """测试 MpFeedback 模型。"""

    def test_tablename(self):
        assert MpFeedback.__tablename__ == "mp_feedbacks"

    def test_has_required_columns(self):
        columns = {c.name for c in MpFeedback.__table__.columns}
        assert "id" in columns
        assert "user_id" in columns
        assert "type" in columns
        assert "content" in columns
        assert "status" in columns
        assert "reply" in columns

    def test_reply_fields(self):
        columns = {c.name for c in MpFeedback.__table__.columns}
        assert "replied_by" in columns
        assert "replied_at" in columns


class TestAllExport:
    """测试 __all__ 导出。"""

    def test_all_exports(self):
        from app.db.models import miniprogram as mod

        assert "MpAddress" in mod.__all__
        assert "MpCart" in mod.__all__
        assert "MpOrder" in mod.__all__
        assert "MpOrderItem" in mod.__all__
        assert "MpFavorite" in mod.__all__
        assert "MpFeedback" in mod.__all__
        assert "MpNotification" in mod.__all__
        assert "MpBrowseHistory" in mod.__all__
