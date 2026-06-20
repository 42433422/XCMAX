"""Tests for app.infrastructure.documents.simple_contract_generator."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.infrastructure.documents.simple_contract_generator import SimpleSalesContractGenerator


class TestSimpleSalesContractGenerator:
    """Tests for SimpleSalesContractGenerator."""

    def test_init_creates_output_dir(self, tmp_path: Path) -> None:
        output_dir = str(tmp_path / "contracts_out")
        gen = SimpleSalesContractGenerator(output_dir=output_dir)
        assert os.path.isdir(output_dir)
        assert gen.output_dir == output_dir

    def test_init_default_output_dir(self) -> None:
        gen = SimpleSalesContractGenerator()
        assert gen.output_dir is not None
        assert os.path.isdir(gen.output_dir)

    def test_generate_with_defaults(self, tmp_path: Path) -> None:
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="测试客户")
        assert result["success"] is True
        assert result["customer_name"] == "测试客户"
        assert result["contract_id"]
        assert result["filename"].endswith(".docx")
        assert os.path.isfile(result["file_path"])

    def test_generate_with_custom_date(self, tmp_path: Path) -> None:
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="客户A", contract_date="2026年01月15日")
        assert result["success"] is True
        assert result["contract_date"] == "2026年01月15日"

    def test_generate_with_custom_products(self, tmp_path: Path) -> None:
        products = [
            {
                "model_number": "100A",
                "name": "测试产品",
                "spec": "5KG×2",
                "unit": "箱",
                "quantity": "20",
                "unit_price": "50.0",
                "amount": "1000",
            },
            {
                "model_number": "200B",
                "name": "另一产品",
                "spec": "10KG×1",
                "unit": "桶",
                "quantity": "5",
                "unit_price": "80.0",
                "amount": "400",
            },
        ]
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="客户B", products=products)
        assert result["success"] is True
        assert result["total_quantity"] == 25.0
        assert result["total_amount"] == 1400.0
        assert result["products"] == products

    def test_generate_with_return_buckets(self, tmp_path: Path) -> None:
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(
            customer_name="客户C",
            return_buckets_expected=3,
            return_buckets_actual=1,
        )
        assert result["success"] is True

    def test_generate_without_return_buckets(self, tmp_path: Path) -> None:
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="客户D")
        assert result["success"] is True

    def test_generate_filename_sanitization(self, tmp_path: Path) -> None:
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="客户/名 称")
        assert result["success"] is True
        assert "/" not in result["filename"]
        assert " " not in result["filename"]

    def test_generate_product_without_model_number(self, tmp_path: Path) -> None:
        products = [
            {
                "model_number": "",
                "name": "无型号产品",
                "spec": "1KG",
                "unit": "袋",
                "quantity": "10",
                "unit_price": "15",
                "amount": "150",
            },
        ]
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="客户E", products=products)
        assert result["success"] is True
        assert result["total_amount"] == 150.0

    def test_generate_empty_products_list(self, tmp_path: Path) -> None:
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="客户F", products=[])
        assert result["success"] is True
        assert result["total_quantity"] == 0
        assert result["total_amount"] == 0
