from __future__ import annotations

import json

import pytest

from app.application.office_parse_app_service import read_workspace_output_files


def test_reads_relative_and_absolute_outputs_inside_workspace(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    output = tmp_path / "outputs" / "data.json"
    output.parent.mkdir()
    output.write_text(json.dumps({"row_count": 3}), encoding="utf-8")

    files = read_workspace_output_files(str(tmp_path), ["outputs/data.json", str(output)])

    assert [item["path"] for item in files] == ["outputs/data.json", "outputs/data.json"]
    assert [item["json"] for item in files] == [{"row_count": 3}, {"row_count": 3}]


def test_rejects_absolute_output_outside_workspace(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text("{}", encoding="utf-8")

    files = read_workspace_output_files(str(tmp_path), [str(outside)])

    assert files == [{"path": str(outside), "kind": "text", "error": "invalid_path"}]


def test_truncated_json_is_not_parsed_even_when_prefix_is_valid(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    output = tmp_path / "large.json"
    output.write_bytes(b'{"row_count": 3}' + b" " * 50)
    result = read_workspace_output_files(str(tmp_path), [output.name], max_bytes=16)[0]
    assert result["truncated"] is True
    assert result["complete"] is False
    assert result["status"] == "partial"
    assert result["error"] == "output_truncated"
    assert result["byte_size"] == output.stat().st_size
    assert result["read_bytes"] == 16
    assert "json" not in result
    assert result["readback_required"] is True
    assert result["readback_path"] == "large.json"


def test_utf8_preview_retains_a_valid_continuation_boundary(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    output = tmp_path / "text.txt"
    output.write_text("ABC中文", encoding="utf-8")
    result = read_workspace_output_files(str(tmp_path), [output.name], max_bytes=5)[0]
    assert result["text"] == "ABC"
    assert result["next_byte_offset"] == 3
    assert result["read_bytes"] == 5
    assert result["byte_size"] == 9
    assert output.read_bytes()[result["next_byte_offset"] :].decode() == "中文"


@pytest.mark.parametrize("budget", [0, -1, True, 2_097_153])
def test_output_reader_rejects_unbounded_budget(tmp_path, budget) -> None:
    with pytest.raises(ValueError, match="budget"):
        read_workspace_output_files(str(tmp_path), [], max_bytes=budget)
