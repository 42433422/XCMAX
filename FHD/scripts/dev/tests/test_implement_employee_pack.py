# FHD/scripts/dev/tests/test_implement_employee_pack.py
"""implement_employee_pack 单元测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from implement_employee_pack import (
    TooManyFilesError,
    count_generated_files,
    implement_pack,
)


def _make_proposal() -> dict:
    return {
        "proposal_id": "test-001",
        "department": "engineering",
        "employee_pack": {
            "name": "intent-clerk",
            "prompt_template": "You are an intent clerk...",
            "skills": ["intent-benchmark"],
            "tools": ["read_file"],
            "acceptance_criteria": ["recall >= 0.7"],
        },
        "estimated_files": 3,
        "estimated_tokens": 45000,
    }


def test_implement_pack_returns_generated_files(tmp_path):
    proposal = _make_proposal()
    output_dir = tmp_path / "out"
    with patch("implement_employee_pack._call_llm") as mock_llm:
        mock_llm.return_value = {
            "files": [
                {"path": "prompt.txt", "content": "You are..."},
                {"path": "skills.json", "content": "[\"intent-benchmark\"]"},
                {"path": "manifest.json", "content": "{\"name\":\"intent-clerk\"}"},
            ]
        }
        files = implement_pack(proposal, output_dir=output_dir)
    assert len(files) == 3
    for f in files:
        assert f.exists()
    assert (output_dir / "prompt.txt").read_text(encoding="utf-8") == "You are..."


def test_implement_pack_rejects_more_than_5_files(tmp_path):
    proposal = _make_proposal()
    output_dir = tmp_path / "out"
    with patch("implement_employee_pack._call_llm") as mock_llm:
        mock_llm.return_value = {
            "files": [{"path": f"f{i}.txt", "content": "x"} for i in range(6)]
        }
        with pytest.raises(TooManyFilesError):
            implement_pack(proposal, output_dir=output_dir)


def test_count_generated_files_checks_paths_only(tmp_path):
    """路径相同视为同一文件（去重）。"""
    files = [
        {"path": "a.txt", "content": "x"},
        {"path": "a.txt", "content": "y"},
        {"path": "b.txt", "content": "z"},
    ]
    assert count_generated_files(files) == 2


def test_implement_pack_writes_ledger_event(tmp_path, monkeypatch):
    proposal = _make_proposal()
    output_dir = tmp_path / "out"
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))

    with patch("implement_employee_pack._call_llm") as mock_llm:
        mock_llm.return_value = {
            "files": [{"path": "prompt.txt", "content": "x"}]
        }
        implement_pack(proposal, output_dir=output_dir)

    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])
    assert evt["event_type"] == "implement_succeeded"
    assert evt["cost_tokens"] >= 0


def test_implement_pack_handles_llm_failure(tmp_path, monkeypatch):
    proposal = _make_proposal()
    output_dir = tmp_path / "out"
    ledger_path = tmp_path / "evolution_decisions.jsonl"
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(ledger_path))

    with patch("implement_employee_pack._call_llm") as mock_llm:
        mock_llm.side_effect = RuntimeError("LLM API error")
        with pytest.raises(RuntimeError, match="LLM API error"):
            implement_pack(proposal, output_dir=output_dir)

    lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    evt = json.loads(lines[0])
    assert evt["event_type"] == "implement_failed"
