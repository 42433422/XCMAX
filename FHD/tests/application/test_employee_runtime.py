# -*- coding: utf-8 -*-
"""employee_runtime 本地 loader / executor / registry 集成。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_csv_read_pack(root: Path, pack_id: str = "csv-full-read-employee") -> Path:
    pack_dir = root / "_employees" / pack_id
    vendor = pack_dir / "backend" / "vendor" / "csv_read"
    vendor.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": pack_id,
        "name": "CSV 读取员工",
        "artifact": "employee_pack",
        "scope": "global",
        "description": "读取 CSV 表格",
        "employee": {"label": "CSV 读取"},
        "employee_config_v2": {
            "actions": {
                "handlers": ["direct_python"],
                "direct_python": {"module": "worker"},
            },
            "cognition": {"agent": {"system_prompt": "读取 CSV"}},
        },
    }
    (pack_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (pack_dir / "rule_spec.json").write_text(
        json.dumps(
            {"runtime_kind": "csv_full_read", "default_output_relpath": "outputs/data.json"}
        ),
        encoding="utf-8",
    )
    (vendor / "convert.py").write_text(
        """from pathlib import Path

def convert_file(src_path, output_path, *, template_path=None, payload=None, ctx=None, rule_spec=None):
    text = Path(src_path).read_text(encoding='utf-8')
    lines = [l for l in text.strip().splitlines() if l]
    cols = lines[0].split(',') if lines else []
    rows = [dict(zip(cols, ln.split(','))) for ln in lines[1:]]
    out = {"columns": cols, "rows": rows, "row_count": len(rows)}
    Path(output_path).write_text(__import__('json').dumps(out), encoding='utf-8')
    return {"output_path": str(output_path), "row_count": len(rows), "column_count": len(cols)}
""",
        encoding="utf-8",
    )
    return pack_dir


@pytest.fixture()
def employee_mods_root(tmp_path, monkeypatch):
    mods_root = tmp_path / "mods"
    mods_root.mkdir()
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(mods_root))
    from app.infrastructure.mods import employee_registry as er
    from app.infrastructure.mods import mod_manager as mm

    er._registry.clear()
    mm._mod_manager = None
    mm._employee_pack_routes_registered.clear()
    from app.application.tools.workflow import invalidate_workflow_tool_registry

    invalidate_workflow_tool_registry()
    return mods_root


def test_loader_parse_v2_and_runtime_probe(employee_mods_root):
    pack_id = "csv-full-read-employee"
    _write_csv_read_pack(employee_mods_root, pack_id)
    from app.application.employee_runtime.loader import (
        load_employee_pack_from_disk,
        pack_has_direct_python_runtime,
        parse_employee_config_v2,
    )

    pack = load_employee_pack_from_disk(pack_id)
    cfg = parse_employee_config_v2(pack["manifest"])
    assert "direct_python" in (cfg.get("actions") or {}).get("handlers", [])
    assert pack_has_direct_python_runtime(Path(pack["pack_dir"]))


def test_tool_registry_uses_pack_id_as_tool_name(employee_mods_root):
    _write_csv_read_pack(employee_mods_root)
    from app.mod_sdk.employee_tool_registry import (
        build_employee_pack_tool_definitions,
        invalidate_employee_tool_cache,
        is_employee_tool,
    )

    invalidate_employee_tool_cache()
    tools = build_employee_pack_tool_definitions()
    names = [t["function"]["name"] for t in tools]
    assert "csv-full-read-employee" in names
    assert is_employee_tool("csv-full-read-employee")


def test_execute_employee_task_local_csv(employee_mods_root, tmp_path):
    pack_id = "csv-full-read-employee"
    _write_csv_read_pack(employee_mods_root, pack_id)
    csv_file = tmp_path / "sample.csv"
    csv_file.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    from app.application.employee_runtime.executor import execute_employee_task_local

    result = execute_employee_task_local(
        pack_id,
        "读取 CSV",
        {"file_path": str(csv_file)},
        workspace_root=str(tmp_path),
    )
    assert result.get("success") is True
    outputs = result.get("result", {}).get("outputs") or []
    assert outputs and outputs[0].get("ok") is True


def test_workflow_registry_includes_employee_tools(employee_mods_root):
    _write_csv_read_pack(employee_mods_root)
    from app.application.tools.workflow import (
        get_workflow_tool_registry,
        invalidate_workflow_tool_registry,
    )

    invalidate_workflow_tool_registry()
    reg = get_workflow_tool_registry()
    names = [item["function"]["name"] for item in reg if item.get("function")]
    assert "csv-full-read-employee" in names


def test_risk_gate_blocks_high_without_token():
    from app.application.employee_runtime.risk_gate import gate_action_or_block

    manifest = {"employee_config_v2": {"risk_level": "high"}}
    gate = gate_action_or_block("test", manifest, ["shell_exec"], {})
    assert gate.get("ok") is False
