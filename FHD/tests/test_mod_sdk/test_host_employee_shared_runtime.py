"""Bundled employees share host SDK behavior, never another pack's identity or paths."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.mod_sdk.employee_failure import _failed
from app.mod_sdk.file_employee_support import FileEmployeeSupport

ROOT = Path(__file__).resolve().parents[2]
OFFICERS = [
    "deploy-release-officer",
    "fhd-core-maintainer",
    "flask-entry-keeper",
    "retention-officer",
    "self-checker",
    "seo-sitemap-curator",
    "task-router-officer",
    "vibe-coding-maintainer",
    "workbench-ux-stylist",
]


def load_officer(pack):
    path = ROOT / "mods" / "_employees" / pack / "backend" / "employees"
    source = path / (pack.replace("-", "_") + ".py")
    spec = importlib.util.spec_from_file_location("runtime_test_" + pack, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("pack", OFFICERS)
@pytest.mark.parametrize("handler", ["echo", "llm_md", "webhook", "agent", "unknown"])
async def test_bundled_handlers_keep_identity_and_results(pack, handler, monkeypatch):
    module = load_officer(pack)
    runtime = module._runtime
    assert runtime._manifest_path() == ROOT / "mods" / "_employees" / pack / "manifest.json"
    assert runtime.employee_id == module.EMPLOYEE_ID == pack
    assert runtime.system_prompt == module.SYSTEM_PROMPT
    assert runtime.label == module.EMPLOYEE_LABEL
    assert runtime.fallback_unknown_handler == (pack == "vibe-coding-maintainer")
    calls = []

    async def llm(messages, **kwargs):
        calls.append(messages)
        return {"ok": True, "content": "verified"}

    async def post(url, **kwargs):
        calls.append(url)
        return {"ok": True, "status": 200, "text": "verified"}

    async def agent(task, **kwargs):
        calls.append(task)
        return {"ok": True, "summary": "verified", "rounds": 2, "tool_calls": [{"tool": "read"}]}

    config = {
        "employee_config_v2": {
            "actions": {"handlers": [handler], "webhook": {"url": "https://example.invalid/hook"}}
        }
    }
    monkeypatch.setattr(runtime, "_load_manifest", lambda: config)
    result = await module.run(
        {"message": "task"},
        {"call_llm": llm, "http_post": post, "agent_runner": SimpleNamespace(run=agent)},
    )
    if handler == "unknown" and pack != "vibe-coding-maintainer":
        assert result["ok"] is False
        assert result["meta"]["employee_id"] == pack
        assert calls == []
    else:
        assert result["ok"] is True
        expected = "llm_md" if handler == "unknown" else handler
        assert result["meta"]["handler"] == expected
        assert result["meta"]["chosen_handler"] == expected
        assert result["meta"]["declared_handlers"] == [handler]
        if handler == "echo":
            assert result["items"] == [{"echo": {"message": "task"}}]
        else:
            assert calls


@pytest.mark.parametrize("pack", OFFICERS)
async def test_missing_manifest_fails_closed_and_offline_plan_keeps_label(pack, monkeypatch):
    module = load_officer(pack)
    monkeypatch.setattr(module._runtime, "_load_manifest", lambda: None)
    denied = await module.run({}, {})
    assert denied["ok"] is False
    assert denied["meta"]["employee_id"] == pack
    monkeypatch.setattr(
        module._runtime,
        "_load_manifest",
        lambda: {"employee_config_v2": {"actions": {"handlers": ["llm_md"]}}},
    )
    offline = await module.run({}, {})
    assert offline["ok"] is True
    assert module.EMPLOYEE_LABEL in offline["summary"]
    assert offline["meta"]["offline"] is True
    assert offline["warnings"]


def test_file_paths_remain_pack_local_and_results_do_not_share_mutable_state(tmp_path):
    first = tmp_path / "first" / "backend" / "employees" / "first.py"
    second = tmp_path / "second" / "backend" / "employees" / "second.py"
    for source in [first, second]:
        source.parent.mkdir(parents=True)
        (source.parents[1] / "template.xlsx").write_bytes(b"template")
    one = FileEmployeeSupport(str(first), {"default_template_relpath": "template.xlsx"})
    two = FileEmployeeSupport(str(second), {"default_template_relpath": "template.xlsx"})
    assert one._resolve_template({}, {}) == first.parents[1] / "template.xlsx"
    assert two._resolve_template({}, {}) == second.parents[1] / "template.xlsx"
    payload = {"workspace_root": str(tmp_path), "file_path": "input.csv"}
    (tmp_path / "input.csv").write_text("a\n1\n")
    assert one._resolve_input(payload, {}) == tmp_path / "input.csv"
    assert one._resolve_output({"workspace_root": str(tmp_path)}, {}).parent.exists()
    a = _failed("no", "denied")
    b = _failed("no", "denied")
    a["evidence"].append("mutated")
    assert b["evidence"] == []
    assert one._ok(None)["items"] == [None]
    assert one._err("x" * 2000)["error"] == "x" * 1000
