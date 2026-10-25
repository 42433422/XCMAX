"""里程碑 S2：Planner 工具执行须经 planner_tools 门面分派。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXCEL_MOD = REPO / "mods" / "xcagi-planner-excel-tools"
if not (EXCEL_MOD / "manifest.json").is_file():
    pytest.skip(
        "xcagi-planner-excel-tools not present in SSOT mods/",
        allow_module_level=True,
    )


def test_planner_excel_tools_manifest_execution_owner():
    data = json.loads((EXCEL_MOD / "manifest.json").read_text(encoding="utf-8"))
    cfg = data.get("config") or {}
    assert cfg.get("tools_execution_owner") == "mod"
    assert "excel_analysis" in (cfg.get("native_planner_tools") or [])


def test_execute_workflow_tool_delegates_to_native_first(monkeypatch):
    from app.application.tools import workflow as wf

    monkeypatch.setattr(
        "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
        lambda *a, **k: ('{"source":"mod:test","success":true}', "xcagi-planner-excel-tools"),
    )
    raw = wf.execute_workflow_tool("excel_analysis", {})
    parsed = json.loads(raw)
    assert parsed.get("source") == "mod:test"


def test_resolve_executor_facade_vs_host(monkeypatch):
    from app.mod_sdk.planner_tools import (
        execute_planner_workflow_tool,
        resolve_planner_tool_executor,
    )

    monkeypatch.setattr(
        "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
        lambda: False,
    )
    assert resolve_planner_tool_executor().__name__ == "execute_workflow_tool"

    monkeypatch.setattr(
        "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
        lambda: True,
    )
    assert resolve_planner_tool_executor().__name__ == "execute_planner_workflow_tool"
    raw = execute_planner_workflow_tool("excel_chart_recommend", {})
    assert "suggestions" in json.loads(raw)


def test_execute_planner_tool_from_body_mod_native_path(monkeypatch):
    from app.mod_sdk.planner_tools import execute_planner_tool_from_body
    from app.shell.xcagi_mods_discover import mods_dir

    monkeypatch.delenv("XCAGI_ROOT", raising=False)
    monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
    monkeypatch.setenv("XCAGI_PLANNER_TOOLS_VIA_MOD", "1")
    assert mods_dir() == REPO / "mods"
    out = execute_planner_tool_from_body({"tool_name": "excel_chart_recommend", "arguments": {}})
    assert out.get("success") is True
    assert out.get("execution_path") == "mod_native"
    assert out.get("mod_id") == "xcagi-planner-excel-tools"


@pytest.mark.parametrize("source", ["canonical", "legacy", "root_env", "mods_env"])
def test_discovery_selects_one_mod_tree_with_explicit_roots_first(tmp_path, monkeypatch, source):
    from app.shell import xcagi_mods_discover as discovery

    repo = tmp_path / "repo"
    canonical, legacy, explicit = (
        repo / "mods",
        repo / "XCAGI" / "mods",
        tmp_path / "custom" / "mods",
    )
    roots = {"canonical": canonical, "legacy": legacy, "root_env": explicit, "mods_env": explicit}
    for index, root in enumerate((canonical, legacy, explicit)):
        if source == "legacy" and root == canonical:
            continue
        mod = root / "same-mod"
        mod.mkdir(parents=True)
        (mod / "manifest.json").write_text(json.dumps({"id": "same-mod", "version": str(index)}))
    monkeypatch.setattr(discovery, "__file__", str(repo / "app" / "shell" / "discovery.py"))
    monkeypatch.setattr(discovery, "_effective_single_mod_id", lambda: None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("XCAGI_ROOT", raising=False)
    monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
    if source == "root_env":
        monkeypatch.setenv("XCAGI_ROOT", str(explicit.parent))
    elif source == "mods_env":
        monkeypatch.setenv("XCAGI_MODS_DIR", str(explicit))

    assert discovery.mods_dir() == roots[source]
    manifests = discovery.read_manifest_dicts()
    assert len(manifests) == 1
    assert manifests[0]["version"] == str(
        {"canonical": 0, "legacy": 1, "root_env": 2, "mods_env": 2}[source]
    )
