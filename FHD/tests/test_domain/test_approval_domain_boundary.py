"""Approval invalid-data handling, private logs and independent domain imports."""

import ast
import json
import logging
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.approval import safe_dsl


@pytest.mark.parametrize(
    "expression,context",
    [
        ("amount > 1", {"amount": None}),
        ("amount > 1", {"amount": "private-business-value"}),
        ("amount < 'private-business-value'", {"amount": 5}),
        ("-amount > 0", {"amount": "private-business-value"}),
        ("+amount > 0", {"amount": None}),
        ("amount + 1 > 0", {"amount": "private-business-value"}),
        ("amount / 0 > 1", {"amount": 1}),
        ("amount ** 1000 > 0", {"amount": 1e300}),
    ],
)
def test_invalid_business_operands_fail_closed(expression, context):
    with pytest.raises(safe_dsl.SafeEvaluationError):
        safe_dsl.evaluate_condition(expression, context)
    node = SimpleNamespace(id="audit-node", condition_expression=expression)
    assert safe_dsl.should_trigger_condition(node, context) is False


@pytest.mark.parametrize(
    "expression,context,expected",
    [
        ("amount > -1", {"amount": Decimal("0")}, True),
        ("-amount = 1.25", {"amount": Decimal("-1.25")}, True),
        ("amount > 0 AND quantity > 0", {"amount": Decimal("10"), "quantity": 2}, True),
        ("amount > 0 AND quantity > 0", {"amount": Decimal("0"), "quantity": 2}, False),
    ],
)
def test_decimal_conditions_remain_supported(expression, context, expected):
    assert safe_dsl.evaluate_condition(expression, context) is expected


@pytest.mark.parametrize(
    "expression",
    [
        "department = 'private-business-value'",
        "department + 1 > 0",
        "department > 'private-business-value' AND (",
        "missing_private_business_value > 1",
    ],
)
def test_logs_do_not_copy_expressions_or_context(expression, caplog):
    with caplog.at_level(logging.DEBUG, logger=safe_dsl.__name__):
        safe_dsl.should_trigger_condition(
            SimpleNamespace(id="private-node-id", condition_expression=expression),
            {"department": "private-business-value"},
        )
    assert "private-business-value" not in caplog.text
    assert "missing_private_business_value" not in caplog.text
    assert "private-node-id" not in caplog.text
    assert expression not in caplog.text


def test_domain_rule_is_mandatory_and_has_no_exemptions():
    root = Path(safe_dsl.__file__).resolve().parents[3]
    config = json.loads((root / "config/import_boundary.yaml").read_text())
    rule = next(r for r in config["rules"] if r["name"] == "approval-domain-no-infrastructure")
    assert rule["required"] is True
    assert rule["allow_files"] == []
    for path in (root / "app/domain/approval").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            imports = (
                [n.name for n in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(
                name == prefix or name.startswith(prefix + ".")
                for name in imports
                for prefix in rule["forbid"]
            ), path


def test_evaluator_loads_without_infrastructure_dependencies():
    path = str(Path(safe_dsl.__file__).resolve())
    code = f"""
import importlib.abc, importlib.util, sys
class DenyInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app" or fullname.split(".")[0] in {{"sqlalchemy", "httpx", "redis"}}:
            raise ImportError("domain imported infrastructure: " + fullname)
sys.meta_path.insert(0, DenyInfrastructure())
spec = importlib.util.spec_from_file_location("approval_domain_isolated", {path!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.evaluate_condition("amount > -1 AND True OR 1 / 0", {{"amount": 0}})
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
