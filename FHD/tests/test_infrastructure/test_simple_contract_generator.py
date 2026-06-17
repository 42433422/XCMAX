"""Tests for app.infrastructure.documents.simple_contract_generator."""
from __future__ import annotations

import os
import pytest

from app.infrastructure.documents.simple_contract_generator import SimpleSalesContractGenerator


class TestSimpleSalesContractGenerator:
    def test_init_default_output_dir(self):
        gen = SimpleSalesContractGenerator()
        assert gen.output_dir is not None
        assert os.path.isdir(gen.output_dir)

    def test_init_custom_output_dir(self, tmp_path):
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        assert gen.output_dir == str(tmp_path)

    def test_generate_creates_file(self, tmp_path):
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="测试客户")
        assert result["success"] is True
        assert os.path.exists(result["file_path"])

    def test_generate_with_custom_date(self, tmp_path):
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="测试客户", contract_date="2026年06月01日")
        assert result["success"] is True
        assert result["contract_date"] == "2026年06月01日"

    def test_generate_with_custom_products(self, tmp_path):
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        products = [
            {
                "model_number": "M1",
                "name": "产品A",
                "spec": "5KG",
                "unit": "箱",
                "quantity": "20",
                "unit_price": "50.0",
                "amount": "1000",
            }
        ]
        result = gen.generate(customer_name="测试客户", products=products)
        assert result["success"] is True
        assert result["total_quantity"] == 20.0
        assert result["total_amount"] == 1000.0

    def test_generate_with_return_buckets(self, tmp_path):
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(
            customer_name="测试客户",
            return_buckets_expected=5,
            return_buckets_actual=3,
        )
        assert result["success"] is True

    def test_generate_without_return_buckets(self, tmp_path):
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="测试客户")
        assert result["success"] is True

    def test_generate_default_products(self, tmp_path):
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="测试客户")
        assert result["success"] is True
        assert len(result["products"]) == 1
        assert result["products"][0]["model_number"] == "306B"

    def test_generate_filename_sanitized(self, tmp_path):
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="测试/客户 名称")
        assert result["success"] is True
        assert "/" not in result["filename"]

    def test_generate_returns_contract_id(self, tmp_path):
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        result = gen.generate(customer_name="测试客户")
        assert result["contract_id"] is not None
        assert len(result["contract_id"]) == 8

    def test_generate_multiple_products(self, tmp_path):
        gen = SimpleSalesContractGenerator(output_dir=str(tmp_path))
        products = [
            {"model_number": "A", "name": "P1", "spec": "1KG", "unit": "箱",
             "quantity": "10", "unit_price": "10", "amount": "100"},
            {"model_number": "B", "name": "P2", "spec": "2KG", "unit": "箱",
             "quantity": "5", "unit_price": "20", "amount": "100"},
        ]
        result = gen.generate(customer_name="测试客户", products=products)
        assert result["success"] is True
        assert result["total_quantity"] == 15.0
        assert result["total_amount"] == 200.0
