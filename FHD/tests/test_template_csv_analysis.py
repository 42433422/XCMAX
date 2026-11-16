"""模板库 CSV 类型分析与保存类别校验。"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.shared_services.document_templates.analyzer import (
    _analyze_csv_template,
    _read_csv_rows,
)


def _write_csv(tmp_path: Path, name: str, text: str, encoding: str = "utf-8") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


def test_read_csv_rows_falls_back_to_gb18030(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "orders.csv", "客户,数量\n甲公司,3\n", encoding="gb18030")

    rows = _read_csv_rows(str(path))

    assert rows[0] == ["客户", "数量"]
    assert rows[1] == ["甲公司", "3"]


def test_analyze_csv_template_returns_csv_fields_and_grid(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "orders.csv", "客户,数量\n甲公司,3\n乙公司,5\n")

    resp = _analyze_csv_template(str(path), "", "orders.csv", "task-csv", "")

    payload = json.loads(resp.body)
    assert payload["success"] is True
    assert payload["template_type"] == "csv"
    assert [f["label"] for f in payload["fields"]] == ["客户", "数量"]
    preview = payload["preview_data"]
    assert preview["file_path"] == str(path)
    assert preview["grid_preview"]["rows"][1] == ["甲公司", "3"]
    assert preview["sample_rows"][0] == {"客户": "甲公司", "数量": "3"}
