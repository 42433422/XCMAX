# mypy: disable-error-code="import-not-found"
# FHD/scripts/dev/tests/test_retry_with_adjusted_prompt.py
"""retry_with_adjusted_prompt 单元测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from retry_with_adjusted_prompt import (
    MAX_RETRIES,
    adjust_prompt_for_retry,
    run_with_retries,
)


def test_adjust_prompt_retry_1_appends_failure_reason():
    base_prompt = "Implement X."
    failure_reason = "arch_fitness failed: imports outside DDD layers"
    adjusted = adjust_prompt_for_retry(base_prompt, retry_count=1, failure_reason=failure_reason)
    assert failure_reason in adjusted
    assert "Implement X." in adjusted


def test_adjust_prompt_retry_2_asks_simplify():
    base_prompt = "Implement X."
    adjusted = adjust_prompt_for_retry(base_prompt, retry_count=2, failure_reason="x")
    assert "简化设计" in adjusted or "simplify" in adjusted.lower()
    assert "3" in adjusted  # "files <= 3"


def test_adjust_prompt_retry_3_asks_minimal():
    base_prompt = "Implement X."
    adjusted = adjust_prompt_for_retry(base_prompt, retry_count=3, failure_reason="x")
    assert "最小化" in adjusted or "minimal" in adjusted.lower()
    assert "1" in adjusted  # only 1 file


def test_run_with_retries_succeeds_on_first_try():
    """第 1 次成功，不重试。"""
    call_count = {"n": 0}

    def action(prompt: str):
        call_count["n"] += 1
        return {"success": True, "files": ["a.txt"]}

    result = run_with_retries(
        base_prompt="Implement X.",
        action=action,
        failure_checker=lambda r: (False, None) if r.get("success") else (True, "no success"),
    )
    assert result["success"] is True
    assert call_count["n"] == 1


def test_run_with_retries_succeeds_on_third_try():
    """前 2 次失败，第 3 次成功。"""
    call_count = {"n": 0}

    def action(prompt: str):
        call_count["n"] += 1
        if call_count["n"] < 3:
            return {"success": False}
        return {"success": True}

    result = run_with_retries(
        base_prompt="Implement X.",
        action=action,
        failure_checker=lambda r: (False, None) if r.get("success") else (True, "no success"),
    )
    assert result["success"] is True
    assert call_count["n"] == 3


def test_run_with_retries_fails_after_max():
    """3 次都败，返回最终失败。"""
    call_count = {"n": 0}

    def action(prompt: str):
        call_count["n"] += 1
        return {"success": False}

    result = run_with_retries(
        base_prompt="Implement X.",
        action=action,
        failure_checker=lambda r: (True, "always fail"),
    )
    assert result["success"] is False
    assert call_count["n"] == MAX_RETRIES
    assert "always fail" in result["failure_reasons"][-1]


def test_run_with_retries_writes_ledger(tmp_path, monkeypatch):
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))

    run_with_retries(
        base_prompt="Implement X.",
        action=lambda p: {"success": False},
        failure_checker=lambda r: (True, "x"),
        proposal={"proposal_id": "test"},
    )
    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    # 3 次 retry 失败 = 3 个失败事件 + 1 个最终 needs_human 事件（共 4 行）
    assert len(lines) == MAX_RETRIES + 1
    final = json.loads(lines[-1])
    assert final["event_type"] == "implement_failed"
    assert final["final_status"] == "needs_human"
