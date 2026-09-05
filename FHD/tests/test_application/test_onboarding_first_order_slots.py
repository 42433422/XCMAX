"""Onboarding slot semantics and bounded regression for unterminated quotes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.application.workflow.planner_llmworkflowplanner_mixin02 import (
    _onboarding_first_order_slots,
)


@pytest.mark.parametrize("opening", ["「", "“", '"', "'"])
@pytest.mark.parametrize("closing", ["」", "”", '"', "'"])
@pytest.mark.parametrize("product_prefix", ["查询商品", "查询产品"])
def test_quote_styles_whitespace_and_product_alias(opening, closing, product_prefix):
    message = (
        f"新手第一单：查询客户\t\u3000{opening}  演示 客户  {closing}；"
        f"{product_prefix}\n{opening}\t中文产品 PM-001 \n{closing}；创建演示出货单"
    )
    assert _onboarding_first_order_slots(message) == ("演示 客户", "中文产品 PM-001")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("查询客户「首个」查询客户「后续」 查询商品「商品」", ("首个", "商品")),
        ("查询客户「」查询客户「可用」 查询商品「商品」", ("可用", "商品")),
        ("查询客户「  」查询客户「可用」 查询商品「商品」", None),
        ("查询客户\t无引号 查询客户「可用」 查询产品「商品」", ("可用", "商品")),
        ("查询客户查询客户「可用」 查询商品「商品」", ("可用", "商品")),
        ("查询客户「客户 查询产品「商品」", ("客户 查询产品「商品", "商品")),
        ("查询客户「甲查询客户「乙」 查询商品「商品」", ("甲查询客户「乙", "商品")),
        ("查询产品「先商品」 查询商品「后商品」 查询客户「客户」", ("客户", "先商品")),
        ("查询客户「客户」 查询商品「未闭合", None),
        ("查询客户「客户」 查询商品「」", None),
    ],
)
def test_first_match_and_overlapping_marker_semantics(body, expected):
    assert _onboarding_first_order_slots(f"新手第一单 {body} 演示出货单") == expected


@pytest.mark.parametrize("prefix", ["", "新手第一单", "演示出货单"])
def test_both_onboarding_markers_are_required(prefix):
    assert _onboarding_first_order_slots(f"{prefix} 查询客户「客户」 查询商品「商品」") is None


@pytest.mark.parametrize(
    "marker", ["查询客户「", "查询商品「", "查询产品「", "查询客户「」", "查询商品「」"]
)
def test_many_invalid_candidates_finish_in_isolated_process(marker):
    source = (
        Path(__file__).resolve().parents[2]
        / "app/application/workflow/planner_llmworkflowplanner_mixin02.py"
    )
    code = """
import json, runpy, sys
parse = runpy.run_path(sys.argv[1])["_onboarding_first_order_slots"]
message = "新手第一单 演示出货单 " + sys.argv[2] * 80000
print(json.dumps(parse(message)))
"""
    # A generous process-level deadline avoids hanging the test worker on regression.
    # Unterminated candidates previously rescanned every suffix. Empty candidates
    # also guard against repeated suffix searches for an absent quote style.
    result = subprocess.run(
        [sys.executable, "-c", code, str(source), marker],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    assert json.loads(result.stdout) is None
