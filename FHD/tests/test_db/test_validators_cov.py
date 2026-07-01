"""Behavioral coverage for the per-model @validates closures in app/db/validators.py.

These cover the private `_register_*_validators` factories (lines 100-227). Each
factory installs a set of `@validates(field)` closures on the model class via the
SQLAlchemy `validates` decorator. We intercept that decorator to capture the real
closures and then exercise them exactly as SQLAlchemy would (``fn(self, key, value)``).

The `self` argument is genuinely unused by every closure (they validate `value`
only), so passing a plain ``object()`` exercises the *real* validation logic — no
source behavior is stubbed out.

Each test pins the *exact* observable behavior, distinguishing two code paths that
are easy to conflate:

* **String/name validators** return ``str(value).strip()`` — they coerce to ``str``
  and strip surrounding whitespace.
* **Numeric/phone validators** delegate to ``ModelValidators`` for *validation only*
  and then return the **original, un-coerced** ``value`` object. Passing a numeric
  *string* therefore returns the string, not a float; passing ``int`` returns ``int``.
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
    """Run ``register_fn`` against a throwaway class, capturing every @validates
    closure keyed by the field name it was registered for.

    We temporarily rebind ``app.db.validators.validates`` (the name the module
    looked up at import time) to a recorder so the real ``@validates(...)``
    decorations inside the factory hand us their closures instead of mutating a
    SQLAlchemy mapper.
    """
    import app.db.validators as _mod

    collected: dict[str, object] = {}

    class _FakeValidates:
        def __init__(self, *fields):
            self.fields = fields

        def __call__(self, fn):
            for f in self.fields:
                collected[f] = fn
            return fn

    original = _mod.validates
    _mod.validates = _FakeValidates  # type: ignore[attr-defined]
    try:
        register_fn(type("Dummy", (), {}))
    finally:
        _mod.validates = original

    return collected


# A sentinel ``self`` proving the closures never touch the instance.
_SELF = object()


def test_extract_collects_exact_field_set_per_model():
    """The factories register exactly the documented fields — no more, no less."""
    assert set(_extract_validators(_register_product_validators)) == {
        "name",
        "price",
        "quantity",
    }
    assert set(_extract_validators(_register_purchase_unit_validators)) == {
        "unit_name",
        "contact_phone",
    }
    assert set(_extract_validators(_register_customer_validators)) == {
        "customer_name",
        "contact_phone",
    }
    assert set(_extract_validators(_register_material_validators)) == {
        "name",
        "material_code",
        "quantity",
        "unit_price",
    }
    assert set(_extract_validators(_register_shipment_validators)) == {
        "purchase_unit",
        "product_name",
        "quantity_kg",
        "quantity_tins",
        "unit_price",
        "amount",
    }


# ---------------------------------------------------------------------------
# _register_product_validators
# ---------------------------------------------------------------------------


class TestProductValidators:
    def setup_method(self):
        self.v = _extract_validators(_register_product_validators)

    # --- name: coerce to str + strip; reject falsy/whitespace -------------
    def test_name_returns_value_unchanged_when_clean(self):
        assert self.v["name"](_SELF, "name", "Widget") == "Widget"

    def test_name_strips_surrounding_whitespace(self):
        assert self.v["name"](_SELF, "name", "  Widget  ") == "Widget"

    def test_name_coerces_non_string_to_stripped_str(self):
        # int input goes through str(value).strip() -> "123", a str not an int.
        result = self.v["name"](_SELF, "name", 123)
        assert result == "123"
        assert isinstance(result, str)

    def test_name_empty_string_raises_with_message(self):
        with pytest.raises(ValueError, match="^产品名称不能为空$"):
            self.v["name"](_SELF, "name", "")

    def test_name_whitespace_only_raises(self):
        # Exercises the `not str(value).strip()` branch (value itself is truthy).
        with pytest.raises(ValueError, match="产品名称不能为空"):
            self.v["name"](_SELF, "name", "   ")

    def test_name_none_raises(self):
        with pytest.raises(ValueError, match="产品名称不能为空"):
            self.v["name"](_SELF, "name", None)

    # --- price: validate >= 0, return ORIGINAL value un-coerced -----------
    def test_price_none_passes_through_as_none(self):
        assert self.v["price"](_SELF, "price", None) is None

    def test_price_returns_original_object_not_coerced(self):
        # validate_positive_number only *checks*; the closure returns `value`.
        # A numeric string therefore stays a string.
        result = self.v["price"](_SELF, "price", "99.9")
        assert result == "99.9"
        assert isinstance(result, str)

    def test_price_zero_is_allowed_and_returns_int_zero(self):
        result = self.v["price"](_SELF, "price", 0)
        assert result == 0
        assert isinstance(result, int)

    def test_price_negative_raises_non_negative_message(self):
        with pytest.raises(ValueError, match="产品价格 必须为非负数"):
            self.v["price"](_SELF, "price", -1)

    def test_price_non_numeric_string_raises_invalid_number(self):
        with pytest.raises(ValueError, match="产品价格 必须是有效数字"):
            self.v["price"](_SELF, "price", "abc")

    # --- quantity: validate >= 0, return original -------------------------
    def test_quantity_none_passes_through(self):
        assert self.v["quantity"](_SELF, "quantity", None) is None

    def test_quantity_zero_allowed(self):
        assert self.v["quantity"](_SELF, "quantity", 0) == 0

    def test_quantity_negative_raises(self):
        with pytest.raises(ValueError, match="产品数量 必须为非负数"):
            self.v["quantity"](_SELF, "quantity", -5)


# ---------------------------------------------------------------------------
# _register_purchase_unit_validators
# ---------------------------------------------------------------------------


class TestPurchaseUnitValidators:
    def setup_method(self):
        self.v = _extract_validators(_register_purchase_unit_validators)

    def test_unit_name_strips_and_returns(self):
        assert self.v["unit_name"](_SELF, "unit_name", "  Corp A  ") == "Corp A"

    def test_unit_name_empty_raises_customer_name_message(self):
        # NB: purchase-unit name reuses the "客户名称" message string.
        with pytest.raises(ValueError, match="客户名称不能为空"):
            self.v["unit_name"](_SELF, "unit_name", "")

    def test_unit_name_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="客户名称不能为空"):
            self.v["unit_name"](_SELF, "unit_name", "   ")

    def test_unit_name_none_raises(self):
        with pytest.raises(ValueError, match="客户名称不能为空"):
            self.v["unit_name"](_SELF, "unit_name", None)

    # --- contact_phone: validate format, return ORIGINAL value ------------
    def test_phone_none_passes_through(self):
        assert self.v["contact_phone"](_SELF, "contact_phone", None) is None

    def test_phone_empty_string_passes_through_unchanged(self):
        # `if value:` is False for "" -> validation skipped, original returned.
        assert self.v["contact_phone"](_SELF, "contact_phone", "") == ""

    def test_phone_valid_returns_original_string(self):
        result = self.v["contact_phone"](_SELF, "contact_phone", "13800138000")
        assert result == "13800138000"

    def test_phone_accepts_punctuation_and_plus(self):
        val = "+86 (010)-1234567"
        assert self.v["contact_phone"](_SELF, "contact_phone", val) == val

    def test_phone_invalid_chars_raise(self):
        with pytest.raises(ValueError, match="电话号码格式不正确"):
            self.v["contact_phone"](_SELF, "contact_phone", "not-a-phone!!!")

    def test_phone_too_short_raises(self):
        # 6 digits is below the 7-char minimum of the regex.
        with pytest.raises(ValueError, match="电话号码格式不正确"):
            self.v["contact_phone"](_SELF, "contact_phone", "123456")

    def test_phone_too_long_raises(self):
        # 21 chars exceeds the 20-char maximum of the regex.
        with pytest.raises(ValueError, match="电话号码格式不正确"):
            self.v["contact_phone"](_SELF, "contact_phone", "1" * 21)


# ---------------------------------------------------------------------------
# _register_customer_validators
# ---------------------------------------------------------------------------


class TestCustomerValidators:
    def setup_method(self):
        self.v = _extract_validators(_register_customer_validators)

    def test_customer_name_strips_and_returns(self):
        assert self.v["customer_name"](_SELF, "customer_name", "  Big Co  ") == "Big Co"

    def test_customer_name_blank_raises(self):
        with pytest.raises(ValueError, match="客户名称不能为空"):
            self.v["customer_name"](_SELF, "customer_name", "  ")

    def test_customer_name_empty_raises(self):
        with pytest.raises(ValueError, match="客户名称不能为空"):
            self.v["customer_name"](_SELF, "customer_name", "")

    def test_customer_name_none_raises(self):
        with pytest.raises(ValueError, match="客户名称不能为空"):
            self.v["customer_name"](_SELF, "customer_name", None)

    def test_customer_phone_none_passes_through(self):
        assert self.v["contact_phone"](_SELF, "contact_phone", None) is None

    def test_customer_phone_valid_returns_original(self):
        result = self.v["contact_phone"](_SELF, "contact_phone", "+8613800138000")
        assert result == "+8613800138000"

    def test_customer_phone_invalid_raises(self):
        with pytest.raises(ValueError, match="电话号码格式不正确"):
            self.v["contact_phone"](_SELF, "contact_phone", "abc!xyz")


# ---------------------------------------------------------------------------
# _register_material_validators
# ---------------------------------------------------------------------------


class TestMaterialValidators:
    def setup_method(self):
        self.v = _extract_validators(_register_material_validators)

    def test_material_name_strips_and_returns(self):
        assert self.v["name"](_SELF, "name", "  Steel  ") == "Steel"

    def test_material_name_empty_raises(self):
        with pytest.raises(ValueError, match="材料名称不能为空"):
            self.v["name"](_SELF, "name", "")

    def test_material_name_whitespace_raises(self):
        with pytest.raises(ValueError, match="材料名称不能为空"):
            self.v["name"](_SELF, "name", "   ")

    def test_material_name_none_raises(self):
        with pytest.raises(ValueError, match="材料名称不能为空"):
            self.v["name"](_SELF, "name", None)

    def test_material_code_strips_and_returns(self):
        assert self.v["material_code"](_SELF, "material_code", "  MT001  ") == "MT001"

    def test_material_code_empty_raises(self):
        with pytest.raises(ValueError, match="材料编码不能为空"):
            self.v["material_code"](_SELF, "material_code", "")

    def test_material_code_whitespace_raises(self):
        with pytest.raises(ValueError, match="材料编码不能为空"):
            self.v["material_code"](_SELF, "material_code", "  ")

    def test_material_code_none_raises(self):
        with pytest.raises(ValueError, match="材料编码不能为空"):
            self.v["material_code"](_SELF, "material_code", None)

    def test_material_quantity_none_passes_through(self):
        assert self.v["quantity"](_SELF, "quantity", None) is None

    def test_material_quantity_zero_allowed(self):
        assert self.v["quantity"](_SELF, "quantity", 0) == 0

    def test_material_quantity_positive_returns_original(self):
        result = self.v["quantity"](_SELF, "quantity", 10)
        assert result == 10
        assert isinstance(result, int)

    def test_material_quantity_negative_raises(self):
        with pytest.raises(ValueError, match="材料数量 必须为非负数"):
            self.v["quantity"](_SELF, "quantity", -1)

    def test_material_unit_price_none_passes_through(self):
        assert self.v["unit_price"](_SELF, "unit_price", None) is None

    def test_material_unit_price_returns_original_float(self):
        result = self.v["unit_price"](_SELF, "unit_price", 5.5)
        assert result == 5.5
        assert isinstance(result, float)

    def test_material_unit_price_negative_raises(self):
        with pytest.raises(ValueError, match="材料单价 必须为非负数"):
            self.v["unit_price"](_SELF, "unit_price", -0.01)


# ---------------------------------------------------------------------------
# _register_shipment_validators
# ---------------------------------------------------------------------------


class TestShipmentValidators:
    def setup_method(self):
        self.v = _extract_validators(_register_shipment_validators)

    # --- purchase_unit (string) ------------------------------------------
    def test_purchase_unit_strips_and_returns(self):
        assert self.v["purchase_unit"](_SELF, "purchase_unit", "  Acme  ") == "Acme"

    def test_purchase_unit_empty_raises(self):
        with pytest.raises(ValueError, match="购买单位不能为空"):
            self.v["purchase_unit"](_SELF, "purchase_unit", "")

    def test_purchase_unit_whitespace_raises(self):
        with pytest.raises(ValueError, match="购买单位不能为空"):
            self.v["purchase_unit"](_SELF, "purchase_unit", "   ")

    def test_purchase_unit_none_raises(self):
        with pytest.raises(ValueError, match="购买单位不能为空"):
            self.v["purchase_unit"](_SELF, "purchase_unit", None)

    # --- product_name (string) -------------------------------------------
    def test_product_name_strips_and_returns(self):
        assert self.v["product_name"](_SELF, "product_name", "  Widget  ") == "Widget"

    def test_product_name_empty_raises(self):
        with pytest.raises(ValueError, match="产品名称不能为空"):
            self.v["product_name"](_SELF, "product_name", "")

    def test_product_name_none_raises(self):
        with pytest.raises(ValueError, match="产品名称不能为空"):
            self.v["product_name"](_SELF, "product_name", None)

    # --- quantity_kg: required, strictly positive (allow_zero=False) ------
    def test_quantity_kg_none_raises_required(self):
        with pytest.raises(ValueError, match="^重量不能为空$"):
            self.v["quantity_kg"](_SELF, "quantity_kg", None)

    def test_quantity_kg_zero_raises_must_be_positive(self):
        # Distinct path from None: validate_positive_number(allow_zero=False).
        with pytest.raises(ValueError, match="重量 必须为正数"):
            self.v["quantity_kg"](_SELF, "quantity_kg", 0)

    def test_quantity_kg_negative_raises_must_be_positive(self):
        with pytest.raises(ValueError, match="重量 必须为正数"):
            self.v["quantity_kg"](_SELF, "quantity_kg", -3)

    def test_quantity_kg_positive_returns_original(self):
        result = self.v["quantity_kg"](_SELF, "quantity_kg", 50.5)
        assert result == 50.5
        assert isinstance(result, float)

    # --- quantity_tins: required, strictly positive ----------------------
    def test_quantity_tins_none_raises_required(self):
        with pytest.raises(ValueError, match="^桶数不能为空$"):
            self.v["quantity_tins"](_SELF, "quantity_tins", None)

    def test_quantity_tins_zero_raises_must_be_positive(self):
        with pytest.raises(ValueError, match="桶数 必须为正数"):
            self.v["quantity_tins"](_SELF, "quantity_tins", 0)

    def test_quantity_tins_non_numeric_raises_invalid_number(self):
        with pytest.raises(ValueError, match="桶数 必须是有效数字"):
            self.v["quantity_tins"](_SELF, "quantity_tins", "xx")

    def test_quantity_tins_positive_returns_original_int(self):
        result = self.v["quantity_tins"](_SELF, "quantity_tins", 3)
        assert result == 3
        assert isinstance(result, int)

    # --- unit_price: optional, allow_zero=True ---------------------------
    def test_unit_price_none_passes_through(self):
        assert self.v["unit_price"](_SELF, "unit_price", None) is None

    def test_unit_price_zero_allowed(self):
        assert self.v["unit_price"](_SELF, "unit_price", 0) == 0

    def test_unit_price_positive_returns_original(self):
        assert self.v["unit_price"](_SELF, "unit_price", 10.5) == 10.5

    def test_unit_price_negative_raises(self):
        with pytest.raises(ValueError, match="单价 必须为非负数"):
            self.v["unit_price"](_SELF, "unit_price", -1)

    # --- amount: optional, allow_zero=True -------------------------------
    def test_amount_none_passes_through(self):
        assert self.v["amount"](_SELF, "amount", None) is None

    def test_amount_returns_original_object_un_coerced(self):
        # Numeric string is validated but returned as-is (still a str).
        result = self.v["amount"](_SELF, "amount", "5.5")
        assert result == "5.5"
        assert isinstance(result, str)

    def test_amount_positive_returns_original_int(self):
        assert self.v["amount"](_SELF, "amount", 500) == 500

    def test_amount_negative_raises(self):
        with pytest.raises(ValueError, match="金额 必须为非负数"):
            self.v["amount"](_SELF, "amount", -1)
