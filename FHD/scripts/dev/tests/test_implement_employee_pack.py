# FHD/scripts/dev/tests/test_implement_employee_pack.py
"""implement_employee_pack 单元测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from implement_employee_pack import (
    implement_pack,
    count_generated_files,
    TooManyFilesError,
    _build_implementation_prompt,
    MAX_FILES,
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


# --------------------------------------------------------------------------- #
# T-C08: Top1 根因（LLM >5 files）修复 — 强化 prompt 验证
# --------------------------------------------------------------------------- #


class TestBuildImplementationPromptStrengthened:
    """验证 _build_implementation_prompt 包含强化的 5 文件硬约束语言。

    背景：T-C07 审计发现 Top1 根因是 LLM 生成 >5 files（3/9 = 33% 失败），
    原因之一是原 prompt 仅含 "Maximum 5 files" 软约束，LLM 易忽略。
    修复后 prompt 必须：
    1. 明确 HARD LIMIT 语言（让 LLM 知道这是硬阈值）
    2. 显式说明超限会导致整个操作失败（IMMEDIATE failure, NO retry）
    3. 提供 CONSOLIDATE 行动指引（让 LLM 知道超限时该怎么做）
    4. 要求 LLM 在提交前自检文件数（actionable self-check）
    5. 显式给出 MAX_FILES+1 作为失败阈值（让 LLM 知道精确边界）
    """

    def test_prompt_contains_hard_limit_language(self):
        """prompt 必须含 'HARD LIMIT' 字样（强化约束信号）。"""
        prompt = _build_implementation_prompt(_make_proposal())
        assert "HARD LIMIT" in prompt

    def test_prompt_contains_consolidate_guidance(self):
        """prompt 必须含 'CONSOLIDATE' 行动指引（超限时该怎么做）。"""
        prompt = _build_implementation_prompt(_make_proposal())
        assert "CONSOLIDATE" in prompt

    def test_prompt_states_immediate_failure_no_retry(self):
        """prompt 必须明确说明超限导致 IMMEDIATE failure with NO retry。"""
        prompt = _build_implementation_prompt(_make_proposal())
        assert "IMMEDIATE failure" in prompt
        assert "NO retry" in prompt

    def test_prompt_states_explicit_failure_threshold(self):
        """prompt 必须显式给出 MAX_FILES+1 作为失败阈值（让 LLM 知道精确边界）。"""
        prompt = _build_implementation_prompt(_make_proposal())
        # 强化后 prompt: "Generating {MAX_FILES + 1}+ files fails the entire operation."
        assert f"Generating {MAX_FILES + 1}" in prompt

    def test_prompt_requires_self_check_before_submit(self):
        """prompt 必须要求 LLM 在提交前自检文件数。"""
        prompt = _build_implementation_prompt(_make_proposal())
        assert "count your files" in prompt
        assert "consolidate" in prompt.lower()

    def test_prompt_mentions_max_files_multiple_times(self):
        """prompt 必须在多处提及 MAX_FILES（强化信号密度）。

        原 prompt 仅 1 次提及 'Maximum 5 files'；
        强化后至少 3 次：HARD LIMIT 行、Required files 行、CONSOLIDATE 行。
        """
        prompt = _build_implementation_prompt(_make_proposal())
        assert prompt.count(str(MAX_FILES)) >= 3

    def test_prompt_mentions_required_filenames(self):
        """prompt 必须明确列出必备文件名（让 LLM 优先保留这些）。"""
        prompt = _build_implementation_prompt(_make_proposal())
        assert "prompt.txt" in prompt
        assert "skills.json" in prompt
        assert "manifest.json" in prompt


class TestStrengthenedPromptScenarioSimulation:
    """模拟强化 prompt 在同场景下不再因 >5 files 失败。

    T-C08 验收标准：同场景重跑不再同因失败（或测试模拟）。
    本测试通过 mock LLM 模拟：强化 prompt 后，LLM 生成 5 文件（≤ MAX_FILES）→ 成功。
    对照原场景：LLM 生成 6 文件 → TooManyFilesError（仍保留 test_implement_pack_rejects_more_than_5_files 验证）。
    """

    def test_llm_respecting_strengthened_prompt_succeeds_with_exactly_5_files(
        self, tmp_path
    ):
        """模拟 LLM 在强化 prompt 下生成恰好 MAX_FILES 个文件 → 成功。"""
        proposal = _make_proposal()
        output_dir = tmp_path / "out"

        # Mock LLM 模拟"遵循强化 prompt"行为：返回 5 个文件（恰好达到上限）
        with patch("implement_employee_pack._call_llm") as mock_llm:
            mock_llm.return_value = {
                "files": [
                    {"path": "prompt.txt", "content": "You are..."},
                    {"path": "skills.json", "content": '["intent-benchmark"]'},
                    {"path": "manifest.json", "content": '{"name":"x"}'},
                    {"path": "tools.json", "content": "[]"},
                    {"path": "README.md", "content": "# pack"},
                ]
            }
            files = implement_pack(proposal, output_dir=output_dir)

        # 5 文件全部写入，无 TooManyFilesError
        assert len(files) == MAX_FILES
        for f in files:
            assert f.exists()
        assert (output_dir / "prompt.txt").read_text(encoding="utf-8") == "You are..."

    def test_llm_respecting_strengthened_prompt_succeeds_with_fewer_files(
        self, tmp_path
    ):
        """模拟 LLM 在强化 prompt 下选择 CONSOLIDATE 到 3 文件 → 成功。"""
        proposal = _make_proposal()
        output_dir = tmp_path / "out"

        # Mock LLM 模拟"遵循 CONSOLIDATE 指引"行为：合并辅助文档到 prompt.txt
        with patch("implement_employee_pack._call_llm") as mock_llm:
            mock_llm.return_value = {
                "files": [
                    {
                        "path": "prompt.txt",
                        "content": "You are...\n\n## Skills\nintent-benchmark\n\n## README\n# pack",
                    },
                    {"path": "skills.json", "content": '["intent-benchmark"]'},
                    {"path": "manifest.json", "content": '{"name":"x"}'},
                ]
            }
            files = implement_pack(proposal, output_dir=output_dir)

        # 3 文件全部写入（CONSOLIDATE 后），无异常
        assert len(files) == 3
        assert len(files) < MAX_FILES

    def test_strengthened_prompt_does_not_break_existing_5_file_success(self, tmp_path):
        """回归：强化 prompt 不影响 5 文件以内的成功路径。"""
        proposal = _make_proposal()
        output_dir = tmp_path / "out"
        with patch("implement_employee_pack._call_llm") as mock_llm:
            mock_llm.return_value = {
                "files": [
                    {"path": "prompt.txt", "content": "x"},
                    {"path": "skills.json", "content": "[]"},
                    {"path": "manifest.json", "content": "{}"},
                ]
            }
            files = implement_pack(proposal, output_dir=output_dir)
        assert len(files) == 3

    def test_strengthened_prompt_still_rejects_6_files(self, tmp_path):
        """回归：即便 prompt 强化，LLM 仍返 6 文件时仍抛 TooManyFilesError。

        强化 prompt 是预防性措施，不改变硬阈值本身——超过 MAX_FILES 仍必须失败。
        """
        proposal = _make_proposal()
        output_dir = tmp_path / "out"
        with patch("implement_employee_pack._call_llm") as mock_llm:
            mock_llm.return_value = {
                "files": [{"path": f"f{i}.txt", "content": "x"} for i in range(6)]
            }
            with pytest.raises(TooManyFilesError):
                implement_pack(proposal, output_dir=output_dir)


class TestStrengthenedPromptContent:
    """验证强化 prompt 的完整内容（便于审计与回归）。"""

    def test_prompt_includes_proposal_json(self):
        """prompt 必须包含完整 proposal JSON（让 LLM 看到上下文）。"""
        proposal = _make_proposal()
        prompt = _build_implementation_prompt(proposal)
        # proposal 中的字段应出现在 prompt 中
        assert "intent-clerk" in prompt
        assert "engineering" in prompt
        assert "intent-benchmark" in prompt

    def test_prompt_includes_output_json_schema(self):
        """prompt 必须包含输出 JSON schema（让 LLM 知道返回格式）。"""
        prompt = _build_implementation_prompt(_make_proposal())
        assert '"files"' in prompt
        assert '"path"' in prompt
        assert '"content"' in prompt

    def test_prompt_full_text_snapshot(self):
        """prompt 完整文本快照（便于 review 强化语言）。

        若 prompt 文本变更，本测试需同步更新——确保强化语言不被误删。
        """
        prompt = _build_implementation_prompt(_make_proposal())
        # 关键强化短语必须全部出现
        required_phrases = [
            "STRICT CONSTRAINTS",
            "HARD LIMIT",
            "IMMEDIATE failure",
            "NO retry",
            "CONSOLIDATE",
            "count your files",
            f"At most {MAX_FILES} files",
            f"Generating {MAX_FILES + 1}+ files fails",
        ]
        for phrase in required_phrases:
            assert phrase in prompt, f"prompt 缺失强化短语: {phrase!r}"
