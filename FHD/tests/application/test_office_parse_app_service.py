from __future__ import annotations

import json

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
