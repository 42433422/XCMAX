"""customer_mapper 回归测试：

purchase_units 表模型无 discount_rate 列，旧 mapper 直接读 db_model.discount_rate
会抛 AttributeError，导致 SQLAlchemyCustomerRepository 全线不可用。
本测试覆盖：缺列回退默认、显式 0.0 折扣保留、反向 to_db 映射。
"""

from app.db.models.purchase_unit import PurchaseUnit as PurchaseUnitModel
from app.domain.customer.entities import Customer, PurchaseUnit
from app.domain.value_objects import Address, ContactInfo
from app.infrastructure.mappers.customer_mapper import (
    customer_to_domain,
    purchase_unit_to_db,
    purchase_unit_to_domain,
)


def test_purchase_unit_to_domain_missing_discount_rate_uses_default():
    # 真实 ORM 模型实例，未设置（且 schema 无）discount_rate 列
    model = PurchaseUnitModel(unit_name="X")

    domain = purchase_unit_to_domain(model)

    assert isinstance(domain, PurchaseUnit)
    assert domain.unit_name == "X"
    # 缺列时回退到合法默认 1.0（满足领域实体 0<=rate<=1 校验）
    assert domain.discount_rate == 1.0


def test_purchase_unit_to_domain_reads_present_discount_rate():
    # 带 discount_rate 属性的对象应被正确读取，且保留合法的 0.0
    class _WithDiscount:
        id = 7
        unit_name = "Y"
        contact_person = "Alice"
        contact_phone = "123"
        address = "addr"
        discount_rate = 0.0  # 合法 0 折扣，不应被误判回退
        is_active = True
        created_at = None
        updated_at = None

    domain = purchase_unit_to_domain(_WithDiscount())

    assert domain.id == 7
    assert domain.unit_name == "Y"
    assert domain.contact_person == "Alice"
    assert domain.discount_rate == 0.0


def test_purchase_unit_to_domain_none_discount_rate_falls_back():
    class _NoneDiscount:
        id = None
        unit_name = "Z"
        contact_person = None
        contact_phone = None
        address = None
        discount_rate = None
        is_active = False
        created_at = None
        updated_at = None

    domain = purchase_unit_to_domain(_NoneDiscount())

    assert domain.discount_rate == 1.0
    assert domain.is_active is False


def test_purchase_unit_to_db_round_trips_discount_rate():
    unit = PurchaseUnit(unit_name="X", discount_rate=0.5)

    db_dict = purchase_unit_to_db(unit)

    assert db_dict["unit_name"] == "X"
    assert db_dict["discount_rate"] == 0.5
    assert db_dict["is_active"] == 1


def test_customer_to_domain_maps_basic_fields():
    # 旧 mapper 用 ContactInfo(person=..., address=<str>) 调用，
    # 而真实 ContactInfo 字段为 name/phone/address(Address)，会抛 TypeError。
    # 本测试确保映射不再抛错，且核心字段正确落地。
    model = PurchaseUnitModel(unit_name="ACME")

    domain = customer_to_domain(model)

    assert isinstance(domain, Customer)
    assert domain.customer_name == "ACME"
    assert isinstance(domain.contact_info, ContactInfo)
    # contact_person 为空时 ContactInfo.name 归一化为空串，address 缺省为 None
    assert domain.contact_info.name == ""
    assert domain.contact_info.address is None


def test_customer_to_domain_wraps_address_string():
    class _WithContact:
        id = 3
        unit_name = "顺丰"
        contact_person = "张三"
        contact_phone = "13800000000"
        address = "广东 深圳"
        is_active = True
        created_at = None
        updated_at = None

    domain = customer_to_domain(_WithContact())

    assert domain.customer_name == "顺丰"
    assert domain.contact_info.name == "张三"
    assert domain.contact_info.phone == "13800000000"
    # 字符串地址被包装为 Address 值对象，而非原样字符串
    assert isinstance(domain.contact_info.address, Address)
    assert domain.contact_info.address.province == "广东"
    assert domain.contact_info.address.city == "深圳"
