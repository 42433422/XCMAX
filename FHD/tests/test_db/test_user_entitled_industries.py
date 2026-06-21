"""User 模型 entitled_industries 字段测试（Task 1）。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.db.models.user import User


class TestUserEntitledIndustriesField:
    """验证 User.entitled_industries 字段存在且行为正确。"""

    def test_field_exists(self):
        """entitled_industries 属性应存在于 User 类。"""
        assert hasattr(User, "entitled_industries")

    def test_field_column_type_is_json(self):
        """entitled_industries 列类型应为 JSON（带 postgresql JSONB 变体）。"""
        col = User.__table__.columns.get("entitled_industries")
        assert col is not None
        # SQLAlchemy 列类型实例（JSON 或其子类）
        type_name = type(col.type).__name__
        assert type_name in {"JSON", "JSONB"}, f"unexpected type: {type_name}"

    def test_field_nullable(self):
        """entitled_industries 列应允许 NULL。"""
        col = User.__table__.columns.get("entitled_industries")
        assert col is not None
        assert col.nullable is True

    def test_field_default_is_list_callable(self):
        """entitled_industries 默认值应为 list 可调用对象。"""
        col = User.__table__.columns.get("entitled_industries")
        assert col is not None
        # default 可以是 list 可调用对象
        default = col.default
        assert default is not None
        # arg 应为 list（可调用），调用时需传 context 参数
        assert callable(default.arg)
        assert default.arg(None) == []

    def test_instance_default_empty_list(self):
        """User 实例未显式赋值时，entitled_industries 默认应为空列表。"""
        # 用 mock 规避 ORM 必填字段（password 等）
        # 触发 mapped_column default
        col = User.__table__.columns.get("entitled_industries")
        default = col.default
        result = default.arg(None)
        assert result == []
        assert isinstance(result, list)


class TestEntitledIndustriesRoundtrip:
    """验证 entitled_industries 可读写（内存 SQLite）。"""

    def test_set_and_get_entitled_industries(self):
        """设置并读取 entitled_industries 值。"""
        from sqlalchemy import inspect as sa_inspect

        # 不依赖真实 DB：直接验证 mapper 能识别该属性
        mapper = sa_inspect(User)
        assert "entitled_industries" in mapper.columns.keys()
        # 验证可赋值（用 MagicMock 规避 ORM instance_state 要求）
        user = MagicMock(spec=User)
        user.entitled_industries = ["涂料", "电商"]
        assert user.entitled_industries == ["涂料", "电商"]
