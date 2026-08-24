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


def test_loader_falls_back_to_bundled_employee_pack(employee_mods_root, tmp_path, monkeypatch):
    bundled_mods = tmp_path / "bundled-mods"
    pack_dir = _write_csv_read_pack(bundled_mods)
    from app.mod_sdk import edition_policy

    monkeypatch.setattr(edition_policy, "bundled_mods_dir", lambda: bundled_mods)
    from app.application.employee_runtime.loader import load_employee_pack_from_disk

    pack = load_employee_pack_from_disk("csv-full-read-employee")
    assert Path(pack["pack_dir"]) == pack_dir.resolve()


def test_loader_falls_back_to_bundled_employee_when_user_override_is_untrusted(employee_mods_root, tmp_path, monkeypatch):
    user_pack = _write_csv_read_pack(employee_mods_root)
    bundled_mods = tmp_path / "bundled-mods"
    bundled_pack = _write_csv_read_pack(bundled_mods)
    from app.mod_sdk import edition_policy

    monkeypatch.setattr(edition_policy, "bundled_mods_dir", lambda: bundled_mods)
    from app.application.employee_runtime.loader import load_employee_pack_from_disk

    pack = load_employee_pack_from_disk("csv-full-read-employee")
    assert Path(pack["pack_dir"]) == bundled_pack.resolve()
    assert Path(pack["pack_dir"]) != user_pack.resolve()


def test_loader_prefers_signed_user_employee_pack_over_bundle(employee_mods_root, tmp_path, monkeypatch):
    user_pack = _write_csv_read_pack(employee_mods_root)
    bundled_mods = tmp_path / "bundled-mods"
    _write_csv_read_pack(bundled_mods)
    from app.infrastructure.mods.package import compute_directory_hash
    from app.mod_sdk import edition_policy

    monkeypatch.setattr(edition_policy, "bundled_mods_dir", lambda: bundled_mods)
    receipt = {
        "schema_version": 1,
        "signature_verified": True,
        "content_sha256": compute_directory_hash(str(user_pack)),
    }
    (user_pack / ".xcagi-install-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    from app.application.employee_runtime.loader import load_employee_pack_from_disk

    pack = load_employee_pack_from_disk("csv-full-read-employee")
    assert Path(pack["pack_dir"]) == user_pack.resolve()


def test_signed_install_receipt_detects_post_install_tampering(tmp_path):
    pack_dir = _write_csv_read_pack(tmp_path / "outside-source")
    from app.application.employee_runtime.loader import verify_direct_python_pack_trust
    from app.infrastructure.mods.package import compute_directory_hash

    receipt = {
        "schema_version": 1,
        "signature_verified": True,
        "content_sha256": compute_directory_hash(str(pack_dir)),
    }
    (pack_dir / ".xcagi-install-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    assert verify_direct_python_pack_trust(pack_dir)[0] is True

    worker = next((pack_dir / "backend").rglob("*.py"))
    worker.write_text(worker.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    trusted, reason = verify_direct_python_pack_trust(pack_dir)
    assert trusted is False
    assert reason == "installed_pack_content_hash_mismatch"


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


def test_untrusted_writable_employee_python_is_blocked_without_trusted_fallback(employee_mods_root, tmp_path, monkeypatch):
    pack_id = "csv-full-read-employee"
    _write_csv_read_pack(employee_mods_root, pack_id)
    csv_file = tmp_path / "sample.csv"
    csv_file.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    from app.mod_sdk import edition_policy

    monkeypatch.setattr(edition_policy, "bundled_mods_dir", lambda: None)
    from app.application.employee_runtime.executor import execute_employee_task_local

    result = execute_employee_task_local(
        pack_id,
        "读取 CSV",
        {"file_path": str(csv_file)},
        workspace_root=str(tmp_path),
    )
    assert result.get("success") is False
    outputs = result.get("result", {}).get("outputs") or []
    assert outputs and outputs[0].get("ok") is False
    assert outputs[0].get("error_code") == "employee_python_pack_untrusted"


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


def test_risk_gate_auto_approves_registered_high_action(monkeypatch):
    from app.application.employee_runtime.risk_gate import gate_action_or_block
    from app.domain.autonomy.autonomy_guard import reload_autonomy_guard

    monkeypatch.delenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", raising=False)
    reload_autonomy_guard()

    manifest = {"employee_config_v2": {"risk_level": "high"}}
    gate = gate_action_or_block("test", manifest, ["shell_exec"], {})
    assert gate.get("ok") is True
    assert gate.get("risk_level") == "high"
    assert gate.get("decision") == "auto_approve"
