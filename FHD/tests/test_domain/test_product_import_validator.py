"""app/domain/services/product_import_validator 单测。"""

from __future__ import annotations

from app.domain.services.product_import_validator import (
    ProductImportValidator,
    get_product_import_validator,
)


class TestProductImportValidator:
    def test_valid_product(self) -> None:
        result = ProductImportValidator().validate([{"name": "漆", "price": 99.5}])
        assert result.is_valid is True

    def test_missing_name(self) -> None:
        result = ProductImportValidator().validate([{"price": 10}])
        assert result.is_valid is False
        assert any("name" in e.field for e in result.errors)

    def test_missing_price_allowed(self) -> None:
        result = ProductImportValidator().validate([{"name": "漆"}])
        assert result.is_valid is True

    def test_negative_price(self) -> None:
        result = ProductImportValidator().validate([{"name": "漆", "price": -1}])
        assert result.is_valid is False

    def test_name_too_long_warning(self) -> None:
        long_name = "x" * 250
        result = ProductImportValidator().validate([{"name": long_name, "price": 1}])
        assert result.is_valid is True
        assert result.warnings

    def test_empty_list(self) -> None:
        result = ProductImportValidator().validate([])
        assert result.is_valid is False

    def test_to_dict_shape(self) -> None:
        d = ProductImportValidator().validate([{"price": 1}]).to_dict()
        assert "errors" in d and "warnings" in d

    def test_factory(self) -> None:
        assert isinstance(get_product_import_validator(), ProductImportValidator)
