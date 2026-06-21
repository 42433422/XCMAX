"""Extended branch coverage for app/db/validators.py.

The existing test_validators.py covers ModelValidators statics and register_model_validators.
This file covers the private _register_*_validators closures (lines 100–227),
which define inner functions that are exercised by calling them directly with
a mock self-object, mimicking what SQLAlchemy would do via @validates.
"""

from __future__ import annotations

import pytest

from app.db.validators import (
    _register_customer_validators,
    _register_material_validators,
    _register_product_validators,
    _register_purchase_unit_validators,
    _register_shipment_validators,
)

# ---------------------------------------------------------------------------
# Helper: extract the inner validator functions from a _register_* closure
# ---------------------------------------------------------------------------


def _extract_validators(register_fn):
    """
    Call register_fn with a dummy class to collect all @validates closures
    as a dict keyed by field name.

    Patches app.db.validators.validates (the name already bound in that
    module's namespace) so that when the _register_* function executes
    its @validates decorators, we intercept and collect the closures.
    """
    import app.db.validators as _mod

    collected: dict[str, object] = {}

    class _FakeValidates:
        """Stub for the @validates decorator: captures (field, fn)."""

        def __init__(self, *fields):
            self.fields = fields

        def __call__(self, fn):
            for f in self.fields:
                collected[f] = fn
            return fn

    original = _mod.validates
    _mod.validates = _FakeValidates  # type: ignore[attr-defined]
    try:
        dummy_class = type("Dummy", (), {})
        register_fn(dummy_class)
    finally:
        _mod.validates = original

    return collected


# ---------------------------------------------------------------------------
# _register_product_validators
# ---------------------------------------------------------------------------


class TestProductValidators:
    def setup_method(self):
        self.validators = _extract_validators(_register_product_validators)
        self.obj = object()  # self is unused in these closures

    def test_validate_name_valid(self):
        fn = self.validators.get("name")
        if fn is None:
            pytest.skip("Could not extract product name validator")
        result = fn(self.obj, "name", "Widget")
        assert result == "Widget"

    def test_validate_name_strips(self):
        fn = self.validators["name"]
        assert fn(self.obj, "name", "  Widget  ") == "Widget"

    def test_validate_name_empty_raises(self):
        fn = self.validators["name"]
        with pytest.raises(ValueError, match="产品名称"):
            fn(self.obj, "name", "")

    def test_validate_name_none_raises(self):
        fn = self.validators["name"]
        with pytest.raises(ValueError):
            fn(self.obj, "name", None)

    def test_validate_price_none_passthrough(self):
        fn = self.validators["price"]
        assert fn(self.obj, "price", None) is None

    def test_validate_price_valid(self):
        fn = self.validators["price"]
        assert fn(self.obj, "price", 99.9) == 99.9

    def test_validate_price_negative_raises(self):
        fn = self.validators["price"]
        with pytest.raises(ValueError):
            fn(self.obj, "price", -1)

    def test_validate_quantity_none_passthrough(self):
        fn = self.validators["quantity"]
        assert fn(self.obj, "quantity", None) is None

    def test_validate_quantity_zero_ok(self):
        fn = self.validators["quantity"]
        assert fn(self.obj, "quantity", 0) == 0

    def test_validate_quantity_negative_raises(self):
        fn = self.validators["quantity"]
        with pytest.raises(ValueError):
            fn(self.obj, "quantity", -5)


# ---------------------------------------------------------------------------
# _register_purchase_unit_validators
# ---------------------------------------------------------------------------


class TestPurchaseUnitValidators:
    def setup_method(self):
        self.validators = _extract_validators(_register_purchase_unit_validators)
        self.obj = object()

    def test_validate_unit_name_valid(self):
        fn = self.validators.get("unit_name")
        if fn is None:
            pytest.skip("Could not extract purchase unit name validator")
        assert fn(self.obj, "unit_name", "Corp A") == "Corp A"

    def test_validate_unit_name_empty_raises(self):
        fn = self.validators["unit_name"]
        with pytest.raises(ValueError, match="客户名称"):
            fn(self.obj, "unit_name", "")

    def test_validate_unit_name_none_raises(self):
        fn = self.validators["unit_name"]
        with pytest.raises(ValueError):
            fn(self.obj, "unit_name", None)

    def test_validate_contact_phone_none_passthrough(self):
        fn = self.validators["contact_phone"]
        assert fn(self.obj, "contact_phone", None) is None

    def test_validate_contact_phone_valid(self):
        fn = self.validators["contact_phone"]
        result = fn(self.obj, "contact_phone", "13800138000")
        assert result == "13800138000"

    def test_validate_contact_phone_invalid_raises(self):
        fn = self.validators["contact_phone"]
        with pytest.raises(ValueError, match="电话号码"):
            fn(self.obj, "contact_phone", "not-a-phone!!!")


# ---------------------------------------------------------------------------
# _register_customer_validators
# ---------------------------------------------------------------------------


class TestCustomerValidators:
    def setup_method(self):
        self.validators = _extract_validators(_register_customer_validators)
        self.obj = object()

    def test_validate_customer_name_valid(self):
        fn = self.validators.get("customer_name")
        if fn is None:
            pytest.skip("Could not extract customer name validator")
        assert fn(self.obj, "customer_name", "Big Co") == "Big Co"

    def test_validate_customer_name_blank_raises(self):
        fn = self.validators["customer_name"]
        with pytest.raises(ValueError, match="客户名称"):
            fn(self.obj, "customer_name", "  ")

    def test_validate_customer_name_none_raises(self):
        fn = self.validators["customer_name"]
        with pytest.raises(ValueError):
            fn(self.obj, "customer_name", None)

    def test_validate_customer_phone_none_passthrough(self):
        fn = self.validators["contact_phone"]
        assert fn(self.obj, "contact_phone", None) is None

    def test_validate_customer_phone_valid(self):
        fn = self.validators["contact_phone"]
        result = fn(self.obj, "contact_phone", "+8613800138000")
        assert result == "+8613800138000"

    def test_validate_customer_phone_invalid_raises(self):
        fn = self.validators["contact_phone"]
        with pytest.raises(ValueError):
            fn(self.obj, "contact_phone", "abc!xyz")


# ---------------------------------------------------------------------------
# _register_material_validators
# ---------------------------------------------------------------------------


class TestMaterialValidators:
    def setup_method(self):
        self.validators = _extract_validators(_register_material_validators)
        self.obj = object()

    def test_validate_material_name_valid(self):
        fn = self.validators.get("name")
        if fn is None:
            pytest.skip("Could not extract material name validator")
        assert fn(self.obj, "name", "Steel") == "Steel"

    def test_validate_material_name_empty_raises(self):
        fn = self.validators["name"]
        with pytest.raises(ValueError, match="材料名称"):
            fn(self.obj, "name", "")

    def test_validate_material_name_none_raises(self):
        fn = self.validators["name"]
        with pytest.raises(ValueError):
            fn(self.obj, "name", None)

    def test_validate_material_code_valid(self):
        fn = self.validators["material_code"]
        assert fn(self.obj, "material_code", "MT001") == "MT001"

    def test_validate_material_code_empty_raises(self):
        fn = self.validators["material_code"]
        with pytest.raises(ValueError, match="材料编码"):
            fn(self.obj, "material_code", "")

    def test_validate_material_code_none_raises(self):
        fn = self.validators["material_code"]
        with pytest.raises(ValueError):
            fn(self.obj, "material_code", None)

    def test_validate_material_quantity_none_passthrough(self):
        fn = self.validators["quantity"]
        assert fn(self.obj, "quantity", None) is None

    def test_validate_material_quantity_valid(self):
        fn = self.validators["quantity"]
        assert fn(self.obj, "quantity", 10) == 10

    def test_validate_material_price_none_passthrough(self):
        fn = self.validators["unit_price"]
        assert fn(self.obj, "unit_price", None) is None

    def test_validate_material_price_valid(self):
        fn = self.validators["unit_price"]
        assert fn(self.obj, "unit_price", 5.5) == 5.5


# ---------------------------------------------------------------------------
# _register_shipment_validators
# ---------------------------------------------------------------------------


class TestShipmentValidators:
    def setup_method(self):
        self.validators = _extract_validators(_register_shipment_validators)
        self.obj = object()

    def test_validate_purchase_unit_valid(self):
        fn = self.validators.get("purchase_unit")
        if fn is None:
            pytest.skip("Could not extract shipment purchase_unit validator")
        assert fn(self.obj, "purchase_unit", "Acme") == "Acme"

    def test_validate_purchase_unit_empty_raises(self):
        fn = self.validators["purchase_unit"]
        with pytest.raises(ValueError, match="购买单位"):
            fn(self.obj, "purchase_unit", "")

    def test_validate_purchase_unit_none_raises(self):
        fn = self.validators["purchase_unit"]
        with pytest.raises(ValueError):
            fn(self.obj, "purchase_unit", None)

    def test_validate_product_name_valid(self):
        fn = self.validators["product_name"]
        assert fn(self.obj, "product_name", "Widget") == "Widget"

    def test_validate_product_name_empty_raises(self):
        fn = self.validators["product_name"]
        with pytest.raises(ValueError, match="产品名称"):
            fn(self.obj, "product_name", "")

    def test_validate_product_name_none_raises(self):
        fn = self.validators["product_name"]
        with pytest.raises(ValueError):
            fn(self.obj, "product_name", None)

    def test_validate_quantity_kg_none_raises(self):
        fn = self.validators["quantity_kg"]
        with pytest.raises(ValueError, match="重量"):
            fn(self.obj, "quantity_kg", None)

    def test_validate_quantity_kg_zero_raises(self):
        fn = self.validators["quantity_kg"]
        with pytest.raises(ValueError):
            fn(self.obj, "quantity_kg", 0)

    def test_validate_quantity_kg_valid(self):
        fn = self.validators["quantity_kg"]
        assert fn(self.obj, "quantity_kg", 50) == 50

    def test_validate_quantity_tins_none_raises(self):
        fn = self.validators["quantity_tins"]
        with pytest.raises(ValueError, match="桶数"):
            fn(self.obj, "quantity_tins", None)

    def test_validate_quantity_tins_zero_raises(self):
        fn = self.validators["quantity_tins"]
        with pytest.raises(ValueError):
            fn(self.obj, "quantity_tins", 0)

    def test_validate_quantity_tins_valid(self):
        fn = self.validators["quantity_tins"]
        assert fn(self.obj, "quantity_tins", 3) == 3

    def test_validate_unit_price_none_passthrough(self):
        fn = self.validators["unit_price"]
        assert fn(self.obj, "unit_price", None) is None

    def test_validate_unit_price_valid(self):
        fn = self.validators["unit_price"]
        assert fn(self.obj, "unit_price", 10.5) == 10.5

    def test_validate_amount_none_passthrough(self):
        fn = self.validators["amount"]
        assert fn(self.obj, "amount", None) is None

    def test_validate_amount_valid(self):
        fn = self.validators["amount"]
        assert fn(self.obj, "amount", 500) == 500
