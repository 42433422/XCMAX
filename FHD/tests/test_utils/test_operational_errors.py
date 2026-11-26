"""Operational catches must not turn programming errors into successful fallbacks."""

import json
import runpy
from pathlib import Path

import pytest

from app.utils.operational_errors import (
    DATA_SHAPE,
    INFRA_TRANSIENT,
    OPERATIONAL_ERRORS,
    RECOVERABLE_ERRORS,
)


@pytest.mark.parametrize(
    "failure",
    [
        LookupError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        RuntimeError,
        ArithmeticError,
        ZeroDivisionError,
        OverflowError,
        FloatingPointError,
    ],
)
@pytest.mark.parametrize(
    "errors", [DATA_SHAPE, INFRA_TRANSIENT, RECOVERABLE_ERRORS, OPERATIONAL_ERRORS]
)
def test_programming_error_is_not_a_recoverable_failure(failure, errors):
    error = failure("invalid internal contract")
    with pytest.raises(failure) as captured:
        try:
            raise error
        except errors:
            pytest.fail("programming error reached the operational fallback")
    assert captured.value is error


@pytest.mark.parametrize(
    "error",
    [
        OSError("storage unavailable"),
        ConnectionError("provider unavailable"),
        json.JSONDecodeError("invalid external JSON", "{", 1),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid external encoding"),
    ],
)
def test_explicit_external_failures_remain_recoverable(error):
    try:
        raise error
    except RECOVERABLE_ERRORS as caught:
        assert caught is error


def test_ci_gate_rejects_indirect_programming_error_membership(tmp_path):
    gate = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/ci/check_operational_errors_gate.py")
    )
    source = tmp_path / "errors.py"
    source.write_text(
        "INFRA_TRANSIENT = (OSError, RuntimeError)\n"
        "DATA_SHAPE = (LookupError,)\n"
        "RECOVERABLE_ERRORS = INFRA_TRANSIENT + DATA_SHAPE\n"
    )
    check = gate["check_programming_errors_excluded"]
    check.__globals__["SSOT_MODULE"] = source
    problems = check()
    assert any("RECOVERABLE_ERRORS" in item and "KeyError" in item for item in problems)
    assert any("RECOVERABLE_ERRORS" in item and "IndexError" in item for item in problems)
    assert any("INFRA_TRANSIENT" in item and "RuntimeError" in item for item in problems)


def test_ci_gate_rejects_indirect_arithmetic_error_membership(tmp_path):
    gate = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/ci/check_operational_errors_gate.py")
    )
    source = tmp_path / "errors.py"
    source.write_text(
        "INFRA_TRANSIENT = (OSError, ArithmeticError)\n"
        "DATA_SHAPE = (ValueError,)\n"
        "RECOVERABLE_ERRORS = INFRA_TRANSIENT + DATA_SHAPE\n"
    )
    check = gate["check_programming_errors_excluded"]
    check.__globals__["SSOT_MODULE"] = source
    problems = check()
    assert any("ZeroDivisionError" in item for item in problems)
    assert any("ArithmeticError" in item for item in problems)
