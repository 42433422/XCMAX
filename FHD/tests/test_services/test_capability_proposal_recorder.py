"""capability_proposal_recorder 单元测试。

覆盖：
- 空输入拒绝
- 归一化去重（7 天窗口内相同 reason+raw_input 只记一次）
- list_pending_proposals 过滤 / 排序 / 去重
- mark_proposals_processed 写标记
- 文件锁/写入失败容错
- 超过 500 字符截断
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest import mock

import pytest

from app.services import capability_proposal_recorder as recorder


@pytest.fixture
def isolated_proposal_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """每个测试用独立的 jsonl 文件，避免污染彼此。"""
    monkeypatch.setenv("CAPABILITY_PROPOSAL_DIR", str(tmp_path))
    recorder._REPORT_DIR = tmp_path
    recorder._PROPOSAL_FILE = tmp_path / "capability_proposal.jsonl"
    recorder._PROCESSED_FILE = tmp_path / "capability_proposal_processed.jsonl"
    return recorder._PROPOSAL_FILE


class TestNormalize:
    def test_none_returns_empty(self) -> None:
        assert recorder._normalize(None) == ""

    def test_whitespace_collapsed(self) -> None:
        assert recorder._normalize("  foo   bar\n") == "foo bar"

    def test_non_str_coerced(self) -> None:
        assert recorder._normalize(123) == "123"


class TestDedupKey:
    def test_same_input_same_key(self) -> None:
        assert recorder._dedup_key("hello", "intent_unknown") == recorder._dedup_key(
            "hello", "intent_unknown"
        )

    def test_different_reason_different_key(self) -> None:
        assert recorder._dedup_key("hello", "intent_unknown") != recorder._dedup_key(
            "hello", "slot_missing_severe"
        )

    def test_whitespace_only_diff_same_key(self) -> None:
        # 归一化后 "hello   world" == "hello world"
        assert recorder._dedup_key("hello   world", "r") == recorder._dedup_key("hello world", "r")

    def test_case_insensitive(self) -> None:
        assert recorder._dedup_key("Hello", "r") == recorder._dedup_key("HELLO", "r")


class TestRecordCapabilityProposal:
    def test_empty_input_not_recorded(self, isolated_proposal_file: Path) -> None:
        result = recorder.record_capability_proposal(raw_input="", reason="r")
        assert result["recorded"] is False
        assert result["reason"] == "empty_input"
        assert not isolated_proposal_file.exists()

    def test_none_input_not_recorded(self, isolated_proposal_file: Path) -> None:
        result = recorder.record_capability_proposal(raw_input=None, reason="r")
        assert result["recorded"] is False
        assert result["reason"] == "empty_input"

    def test_whitespace_only_not_recorded(self, isolated_proposal_file: Path) -> None:
        result = recorder.record_capability_proposal(raw_input="   \n  ", reason="r")
        assert result["recorded"] is False
        assert result["reason"] == "empty_input"

    def test_first_record_success(self, isolated_proposal_file: Path) -> None:
        result = recorder.record_capability_proposal(
            raw_input="用户问：怎么开发票？",
            reason="intent_unknown",
            context={"intent_result": {"deepseek_intent": "unk"}},
        )
        assert result["recorded"] is True
        assert "dedup_key" in result
        assert result["path"].endswith("capability_proposal.jsonl")
        assert isolated_proposal_file.is_file()

        content = isolated_proposal_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(content) == 1
        rec = json.loads(content[0])
        assert rec["reason"] == "intent_unknown"
        assert rec["raw_input"] == "用户问：怎么开发票？"
        assert rec["source"] == "intent_confirmation_service"
        assert rec["dedup_key"] == result["dedup_key"]
        assert "ts_unix" in rec

    def test_duplicate_within_window_not_recorded(self, isolated_proposal_file: Path) -> None:
        r1 = recorder.record_capability_proposal(raw_input="same input", reason="r")
        r2 = recorder.record_capability_proposal(raw_input="same input", reason="r")
        assert r1["recorded"] is True
        assert r2["recorded"] is False
        assert r2["reason"] == "duplicate"
        assert r2["dedup_key"] == r1["dedup_key"]
        # 文件里仍只有一条
        lines = isolated_proposal_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_different_reason_records_separately(self, isolated_proposal_file: Path) -> None:
        r1 = recorder.record_capability_proposal(raw_input="x", reason="intent_unknown")
        r2 = recorder.record_capability_proposal(raw_input="x", reason="slot_missing")
        assert r1["recorded"] is True
        assert r2["recorded"] is True
        assert r1["dedup_key"] != r2["dedup_key"]

    def test_long_input_truncated(self, isolated_proposal_file: Path) -> None:
        long_text = "a" * 600
        result = recorder.record_capability_proposal(raw_input=long_text, reason="r")
        assert result["recorded"] is True
        lines = isolated_proposal_file.read_text(encoding="utf-8").strip().splitlines()
        rec = json.loads(lines[0])
        assert len(rec["raw_input"]) <= 520  # 500 + 截断后缀
        assert rec["raw_input"].endswith("...(truncated)")

    def test_context_default_empty(self, isolated_proposal_file: Path) -> None:
        recorder.record_capability_proposal(raw_input="x", reason="r")
        lines = isolated_proposal_file.read_text(encoding="utf-8").strip().splitlines()
        rec = json.loads(lines[0])
        assert rec["context"] == {}

    def test_write_failure_returns_false(
        self, isolated_proposal_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 模拟写文件失败：源码用 Path.open()，所以 patch pathlib.Path.open
        from pathlib import Path as _Path

        original_open = _Path.open

        def fake_open(self, mode="r", *args, **kwargs):
            if "a" in str(mode) and "capability_proposal.jsonl" in str(self):
                raise OSError("disk full simulated")
            return original_open(self, mode, *args, **kwargs)

        monkeypatch.setattr(_Path, "open", fake_open)
        result = recorder.record_capability_proposal(raw_input="x", reason="r")
        assert result["recorded"] is False
        assert result["reason"] == "write_failed"


class TestListPendingProposals:
    def test_empty_file_returns_empty(self, isolated_proposal_file: Path) -> None:
        assert recorder.list_pending_proposals() == []

    def test_returns_all_when_since_none(self, isolated_proposal_file: Path) -> None:
        recorder.record_capability_proposal(raw_input="a", reason="r1")
        recorder.record_capability_proposal(raw_input="b", reason="r2")
        pending = recorder.list_pending_proposals()
        assert len(pending) == 2
        # 升序排列
        assert pending[0]["raw_input"] == "a"
        assert pending[1]["raw_input"] == "b"

    def test_filters_by_since_unix(self, isolated_proposal_file: Path) -> None:
        recorder.record_capability_proposal(raw_input="a", reason="r1")
        time.sleep(0.05)
        cutoff = time.time()
        time.sleep(0.05)
        recorder.record_capability_proposal(raw_input="b", reason="r2")
        pending = recorder.list_pending_proposals(since_unix=cutoff)
        assert len(pending) == 1
        assert pending[0]["raw_input"] == "b"

    def test_dedup_keys_in_listing(self, isolated_proposal_file: Path) -> None:
        # 即使 jsonl 中有重复 key（绕过 dedup window 后），listing 也要去重
        recorder.record_capability_proposal(raw_input="a", reason="r1")
        # 模拟时间窗口外的相同记录：直接 append 一条相同 key 但更早 ts
        lines = isolated_proposal_file.read_text(encoding="utf-8").strip().splitlines()
        original = json.loads(lines[0])
        # 手动 append 一条同 key 的旧记录
        with isolated_proposal_file.open("a", encoding="utf-8") as f:
            old_rec = dict(original)
            old_rec["ts_unix"] = original["ts_unix"] - 100  # 更早
            f.write(json.dumps(old_rec, ensure_ascii=False) + "\n")
        pending = recorder.list_pending_proposals()
        # 2 条 jsonl 但只返回 1 条（去重）
        assert len(pending) == 1

    def test_invalid_json_skipped(self, isolated_proposal_file: Path) -> None:
        recorder.record_capability_proposal(raw_input="a", reason="r1")
        with isolated_proposal_file.open("a", encoding="utf-8") as f:
            f.write("not a json line\n")
        pending = recorder.list_pending_proposals()
        assert len(pending) == 1


class TestMarkProposalsProcessed:
    def test_empty_keys_returns_zero(self, isolated_proposal_file: Path) -> None:
        assert recorder.mark_proposals_processed([]) == 0

    def test_writes_marker_file(self, isolated_proposal_file: Path) -> None:
        n = recorder.mark_proposals_processed(["key1", "key2"])
        assert n == 2
        marker = isolated_proposal_file.parent / "capability_proposal_processed.jsonl"
        assert marker.is_file()
        lines = marker.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        rec1 = json.loads(lines[0])
        assert rec1["dedup_key"] == "key1"
        assert "ts" in rec1

    def test_repeated_mark_is_idempotent(self, isolated_proposal_file: Path) -> None:
        assert recorder.mark_proposals_processed(["key1", "key1"]) == 1
        assert recorder.mark_proposals_processed(["key1"]) == 0

    def test_records_disposition_and_issue_receipt(self, isolated_proposal_file: Path) -> None:
        assert (
            recorder.mark_proposals_processed(
                ["key1"],
                disposition="issue_created",
                issue_urls={"key1": "https://github.com/acme/repo/issues/7"},
            )
            == 1
        )
        marker = isolated_proposal_file.parent / "capability_proposal_processed.jsonl"
        receipt = json.loads(marker.read_text(encoding="utf-8"))
        assert receipt["disposition"] == "issue_created"
        assert receipt["issue_url"].endswith("/issues/7")


class TestIntegrationFlow:
    """端到端：记录 → 列举 → 标记 → 列举（不再返回已处理的）。"""

    def test_full_lifecycle(self, isolated_proposal_file: Path) -> None:
        # 1. 记录 2 条提案
        r1 = recorder.record_capability_proposal(
            raw_input="用户问怎么开发票", reason="intent_unknown"
        )
        r2 = recorder.record_capability_proposal(
            raw_input="用户问怎么导出 excel", reason="intent_unknown"
        )
        assert r1["recorded"] and r2["recorded"]

        # 2. 列举待处理
        pending = recorder.list_pending_proposals()
        assert len(pending) == 2

        # 3. 标记 r1 已处理
        n = recorder.mark_proposals_processed([r1["dedup_key"]])
        assert n == 1

        # 4. 再次列举，只剩未处理的 r2
        pending_after = recorder.list_pending_proposals()
        assert [row["dedup_key"] for row in pending_after] == [r2["dedup_key"]]
