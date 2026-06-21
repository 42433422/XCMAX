"""SQLAlchemyCustomerRepository.save_customer 回归测试（无真实 DB）。

旧实现读取 ``customer.contact_info.person`` 并把 Address 值对象直接赋给
DB 的 ``address`` 字符串列，会触发 AttributeError / 落入错误类型。
通过假的 get_db 会话拦截落库对象，断言：
- ``.person`` 已改为 ``.name``；
- Address 值对象被转换为完整地址字符串后再写入 DB 列。
"""

import app.infrastructure.repositories.customer_repository_impl as impl_mod
from app.domain.customer.entities import Customer
from app.infrastructure.repositories.customer_repository_impl import (
    SQLAlchemyCustomerRepository,
)


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeSession:
    def __init__(self, existing=None):
        self._existing = existing
        self.added = []

    def query(self, *args, **kwargs):
        return _FakeQuery(self._existing)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass

    def refresh(self, obj):
        pass


class _FakeDbCtx:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


def _patch_get_db(monkeypatch, session):
    monkeypatch.setattr(impl_mod, "get_db", lambda: _FakeDbCtx(session))


def test_save_customer_insert_converts_address_to_string(monkeypatch):
    session = _FakeSession(existing=None)
    _patch_get_db(monkeypatch, session)

    customer = Customer.create(
        customer_name="顺丰", contact_person="张三", phone="13800000000", address="广东 深圳"
    )

    SQLAlchemyCustomerRepository().save_customer(customer)

    assert len(session.added) == 1
    inserted = session.added[0]
    assert inserted.unit_name == "顺丰"
    # .person -> .name
    assert inserted.contact_person == "张三"
    assert inserted.contact_phone == "13800000000"
    # Address 值对象被转换为字符串再写入 DB 列，而非直接赋 Address
    assert isinstance(inserted.address, str)
    assert inserted.address == "广东深圳"


def test_save_customer_insert_none_address_writes_empty_string(monkeypatch):
    session = _FakeSession(existing=None)
    _patch_get_db(monkeypatch, session)

    customer = Customer.create(customer_name="ACME", contact_person="李四")

    SQLAlchemyCustomerRepository().save_customer(customer)

    inserted = session.added[0]
    assert inserted.contact_person == "李四"
    assert inserted.address == ""


def test_save_customer_update_existing_maps_name_and_address(monkeypatch):
    from app.db.models import PurchaseUnit as PurchaseUnitModel

    existing = PurchaseUnitModel(unit_name="顺丰")
    session = _FakeSession(existing=existing)
    _patch_get_db(monkeypatch, session)

    customer = Customer.create(
        customer_name="顺丰", contact_person="王五", phone="010", address="北京 北京"
    )

    result = SQLAlchemyCustomerRepository().save_customer(customer)

    # 走 update 分支，不会 add 新对象
    assert session.added == []
    assert existing.contact_person == "王五"
    assert existing.contact_phone == "010"
    assert isinstance(existing.address, str)
    assert existing.address == "北京北京"
    # 返回经 mapper 转换的领域对象
    assert result.unit_name == "顺丰"
    assert result.contact_person == "王五"
