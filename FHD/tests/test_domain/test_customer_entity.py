"""Customer 实体回归测试。

历史上 Customer.create / to_dict 仍按旧 ContactInfo 签名调用：
- create() 用 ``ContactInfo(person=..., address=<str>)``，而真实值对象字段为
  ``name`` 且 ``address`` 需要 ``Address`` 值对象 → 运行时抛 TypeError；
- to_dict() 读取 ``contact_info.person`` 并直接序列化 Address → AttributeError。
本测试锁定修复后的行为：name 落位、字符串地址被包装为 Address、to_dict 输出字符串地址。
"""

from app.domain.customer.entities import Customer, PurchaseUnit
from app.domain.value_objects import Address, ContactInfo


def test_create_maps_contact_person_to_name():
    customer = Customer.create(
        customer_name="顺丰", contact_person="张三", phone="13800000000", address="广东 深圳"
    )

    assert customer.customer_name == "顺丰"
    assert isinstance(customer.contact_info, ContactInfo)
    # 旧 person= 关键字已改为 name=
    assert customer.contact_info.name == "张三"
    assert customer.contact_info.phone == "13800000000"
    # 字符串地址被包装为 Address 值对象，而非原样字符串
    assert isinstance(customer.contact_info.address, Address)
    assert customer.contact_info.address.province == "广东"
    assert customer.contact_info.address.city == "深圳"


def test_create_empty_address_yields_none():
    customer = Customer.create(customer_name="ACME")

    assert customer.contact_info.name == ""
    # 空地址不应包装为 Address，而是 None
    assert customer.contact_info.address is None


def test_to_dict_uses_name_and_serializes_address_string():
    customer = Customer.create(
        customer_name="顺丰", contact_person="张三", phone="139", address="广东 深圳"
    )

    data = customer.to_dict()

    assert data["customer_name"] == "顺丰"
    # 旧实现读取 .person 会抛 AttributeError；现读取 .name
    assert data["contact_person"] == "张三"
    assert data["contact_phone"] == "139"
    # Address 被序列化为完整地址字符串，便于 DB/前端消费
    assert data["contact_address"] == "广东深圳"


def test_to_dict_none_address_serializes_to_empty_string():
    customer = Customer.create(customer_name="ACME", contact_person="李四")

    data = customer.to_dict()

    assert data["contact_person"] == "李四"
    # address 为 None 时序列化为空串，保持字符串契约
    assert data["contact_address"] == ""


def test_purchase_unit_get_contact_info_uses_name_and_address_object():
    unit = PurchaseUnit(
        unit_name="仓库A", contact_person="王五", contact_phone="010", address="北京 北京"
    )

    contact = unit.get_contact_info()

    assert isinstance(contact, ContactInfo)
    assert contact.name == "王五"
    assert contact.phone == "010"
    assert isinstance(contact.address, Address)
    assert contact.address.province == "北京"


def test_purchase_unit_get_contact_info_empty_address_is_none():
    unit = PurchaseUnit(unit_name="仓库B")

    contact = unit.get_contact_info()

    assert contact.name == ""
    assert contact.address is None
