"""test_audit_query.py — 三端 audit 查询 CLI 测试。

覆盖：三端查询 + 过滤 + 时间范围 + limit + 文件不存在 + 损坏行容错。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.autonomy.audit_query import (
    AuditEntry,
    default_audit_path,
    format_entry,
    get_nested,
    load_entries,
    main,
    matches_filter,
    parse_filter,
    parse_since,
    query,
)


def make_entry(
    ts: str = "2026-07-18T12:00:00Z",
    kind: str = "health_down",
    action_type: str = "restart_service",
    ok: bool = True,
    root_cause: str = "health_down",
) -> dict:
    return {
        "ts": ts,
        "source_signal": {"kind": kind, "ts": 0, "detail": "test"},
        "diagnosis": {"root_cause": root_cause, "confidence": 0.8, "detail": "d", "evidence": []},
        "action": {"type": action_type, "params": {}, "idempotency_key": "k", "max_attempts": 1, "risk": "low"},
        "result": {"action": {}, "ok": ok, "detail": "ok", "ts": 0},
        "truth_snapshot": {"ts": 0},
    }


def write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


class TestParseSince:
    def test_hours(self):
        dt = parse_since("24h")
        assert dt is not None

    def test_minutes(self):
        dt = parse_since("30m")
        assert dt is not None

    def test_days(self):
        dt = parse_since("7d")
        assert dt is not None

    def test_iso8601(self):
        dt = parse_since("2026-07-18T00:00:00")
        assert dt is not None
        assert dt.year == 2026

    def test_invalid_raises(self):
        with pytest.raises(Exception):
            parse_since("invalid")


class TestParseFilter:
    def test_simple(self):
        k, v = parse_filter("action.type=rollback")
        assert k == "action.type"
        assert v == "rollback"

    def test_no_equals_raises(self):
        with pytest.raises(Exception):
            parse_filter("noequals")


class TestGetNested:
    def test_simple_key(self):
        assert get_nested({"a": 1}, "a") == 1

    def test_nested_path(self):
        assert get_nested({"a": {"b": {"c": 42}}}, "a.b.c") == 42

    def test_missing_key_returns_none(self):
        assert get_nested({"a": 1}, "b") is None

    def test_non_dict_returns_none(self):
        assert get_nested({"a": [1, 2]}, "a.b") is None


class TestMatchesFilter:
    def test_match(self):
        entry = AuditEntry.from_dict(make_entry(action_type="restart_service"))
        assert matches_filter(entry, [("action.type", "restart_service")]) is True

    def test_no_match(self):
        entry = AuditEntry.from_dict(make_entry(action_type="restart_service"))
        assert matches_filter(entry, [("action.type", "rollback")]) is False

    def test_nested_path_match(self):
        entry = AuditEntry.from_dict(make_entry())
        assert matches_filter(entry, [("result.ok", "True")]) is True

    def test_missing_key_no_match(self):
        entry = AuditEntry.from_dict(make_entry())
        assert matches_filter(entry, [("nonexistent.key", "value")]) is False

    def test_multiple_filters_all_must_match(self):
        entry = AuditEntry.from_dict(make_entry(action_type="restart_service", ok=True))
        assert matches_filter(entry, [("action.type", "restart_service"), ("result.ok", "True")]) is True
        assert matches_filter(entry, [("action.type", "restart_service"), ("result.ok", "False")]) is False


class TestLoadEntries:
    def test_load_existing_file(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        write_jsonl(path, [make_entry(), make_entry()])
        entries = load_entries(path)
        assert len(entries) == 2

    def test_nonexistent_returns_empty(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        assert load_entries(path) == []

    def test_corrupted_line_skipped(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        path.write_text('{"ts":"2026"}\nNOT_JSON\n{"ts":"2026"}\n', encoding="utf-8")
        entries = load_entries(path)
        assert len(entries) == 2

    def test_empty_lines_skipped(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        path.write_text('{"ts":"2026"}\n\n\n{"ts":"2026"}\n', encoding="utf-8")
        entries = load_entries(path)
        assert len(entries) == 2


class TestQuery:
    def test_basic_query(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        write_jsonl(path, [make_entry(), make_entry(), make_entry()])
        entries = query("desktop", None, [], 0, path)
        assert len(entries) == 3

    def test_limit(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        write_jsonl(path, [make_entry(ts=f"2026-07-18T12:00:0{i}Z") for i in range(5)])
        entries = query("desktop", None, [], 2, path)
        assert len(entries) == 2  # 取最后 2 条

    def test_filter(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        write_jsonl(path, [
            make_entry(action_type="restart_service"),
            make_entry(action_type="rollback"),
        ])
        entries = query("desktop", None, [("action.type", "rollback")], 0, path)
        assert len(entries) == 1
        assert entries[0].action["type"] == "rollback"

    def test_since_filter(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(days=2)).isoformat()
        new_ts = now.isoformat()
        write_jsonl(path, [make_entry(ts=old_ts), make_entry(ts=new_ts)])
        since = parse_since("24h")
        entries = query("desktop", since, [], 0, path)
        assert len(entries) == 1  # 只有 new 在 24h 内

    def test_nonexistent_path(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        entries = query("desktop", None, [], 0, path)
        assert entries == []


class TestDefaultAuditPath:
    def test_server_path(self):
        p = default_audit_path("server")
        assert str(p) == "/opt/fhd-full/autonomy/audit.jsonl"

    def test_ci_path(self):
        p = default_audit_path("ci")
        assert p.name == "audit.jsonl"

    def test_desktop_path(self):
        p = default_audit_path("desktop")
        assert p.name == "audit.jsonl"

    def test_unknown_source_raises(self):
        with pytest.raises(ValueError):
            default_audit_path("unknown")


class TestFormatEntry:
    def test_format_includes_fields(self):
        entry = AuditEntry.from_dict(make_entry(kind="health_down", action_type="restart_service"))
        out = format_entry(entry, 1)
        assert "health_down" in out
        assert "restart_service" in out
        assert "True" in out

    def test_format_with_none_fields(self):
        entry = AuditEntry(ts="2026", source_signal=None, diagnosis=None, action=None, result=None, truth_snapshot=None)
        out = format_entry(entry, 1)
        assert "?" in out


class TestMain:
    def test_main_no_file_returns_0(self, tmp_path, monkeypatch, capsys):
        # 用自定义 path 指向不存在文件
        rc = main(["--source", "desktop", "--path", str(tmp_path / "no.jsonl")])
        assert rc == 0
        captured = capsys.readouterr()
        assert "无记录" in captured.out

    def test_main_with_entries(self, tmp_path, capsys):
        path = tmp_path / "audit.jsonl"
        write_jsonl(path, [make_entry()])
        rc = main(["--source", "desktop", "--path", str(path), "--limit", "10"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "restart_service" in captured.out
        assert "总计" in captured.out

    def test_main_filter(self, tmp_path, capsys):
        path = tmp_path / "audit.jsonl"
        write_jsonl(path, [
            make_entry(action_type="restart_service"),
            make_entry(action_type="rollback"),
        ])
        rc = main([
            "--source", "desktop", "--path", str(path),
            "--filter", "action.type=rollback",
        ])
        assert rc == 0
        captured = capsys.readouterr()
        assert "rollback" in captured.out
        assert "1 条" in captured.out
