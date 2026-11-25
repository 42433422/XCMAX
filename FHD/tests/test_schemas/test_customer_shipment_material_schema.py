"""customer / shipment / material schema 校验测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.customer_schema import CustomerCompatMutation, CustomerCreate, CustomerUpdate
from app.schemas.material_schema import MaterialCreate, MaterialUpdate
from app.schemas.shipment_schema import ShipmentCreate, ShipmentItemCreate


class TestCustomerSchema:
    def test_create_ok(self):
        c = CustomerCreate(name="  ACME  ", email="a@b.com")
        assert c.name == "ACME"

    def test_create_blank_name_raises(self):
        with pytest.raises(ValidationError):
            CustomerCreate(name="  ")

    def test_create_bad_email_raises(self):
        with pytest.raises(ValidationError):
            CustomerCreate(name="X", email="not-email")

    def test_update_optional(self):
        u = CustomerUpdate()
        assert u.name is None


    def test_legacy_write_aliases_use_backend_validation_and_ignore_client_tenant(self):
        value = CustomerCompatMutation.model_validate(
            {
                "unit_name": "  ACME  ",
                "contact_person": "  李四  ",
                "tenant_id": 999,
                "expected_version": "2",
            }
        )
        assert value.model_dump(exclude_unset=True) == {
            "unit_name": "ACME",
            "contact_person": "李四",
            "expected_version": 2,
        }

    @pytest.mark.parametrize(
        "invalid",
        [
            {"customer_name": "A", "unit_name": "B"},
            {"contact_address": "A", "address": "B"},
            {"unit_name": 11},
            {"unit_name": "X" * 201},
            {"contact_phone": "1" * 51},
            {"expected_version": True},
            {"expected_version": 1.0},
            {"expected_version": -1},
        ],
    )
    def test_legacy_customer_mutations_reject_invalid_contract(self, invalid):
        with pytest.raises(ValidationError):
            CustomerCompatMutation.model_validate(invalid)


class TestShipmentSchema:
    def test_item_quantity_positive(self):
        with pytest.raises(ValidationError):
            ShipmentItemCreate(product_id=1, quantity=0)

    def test_create_requires_items(self):
        with pytest.raises(ValidationError):
            ShipmentCreate(customer_id=1, items=[])

    def test_create_ok(self):
        s = ShipmentCreate(
            customer_id=2,
            items=[ShipmentItemCreate(product_id=1, quantity=1.5)],
        )
        assert len(s.items) == 1


class TestMaterialSchema:
    def test_create_defaults(self):
        m = MaterialCreate(name="钢板")
        assert m.unit == "个"
        assert m.quantity == 0

    def test_material_code_pattern(self):
        with pytest.raises(ValidationError):
            MaterialCreate(name="x", material_code="bad code!")

    def test_material_code_valid(self):
        m = MaterialCreate(name="x", material_code="M-01_a")
        assert m.material_code == "M-01_a"

    def test_update_blank_name_raises(self):
        with pytest.raises(ValidationError):
            MaterialUpdate(name="   ")
