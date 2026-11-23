"""员工目录：对话型（prompt-only）员工只在展示口径中出现。"""

from __future__ import annotations

import app.mod_sdk.employee_directory as employee_directory


def _manifest(pack_id: str, *, prompt: str = "你是对话型专家") -> dict:
    return {
        "id": pack_id,
        "name": "对话型专家",
        "artifact": "employee_pack",
        "employee": {"label": "对话型专家"},
        "employee_config_v2": {
            "identity": {
                "name": "对话型专家",
                "area": "craft-workshop",
                "description": "导入的专家",
            },
            "cognition": {"agent": {"system_prompt": prompt}},
        },
    }


def _patch(monkeypatch, tools: list[dict], records: list[dict]) -> None:
    monkeypatch.setattr(
        "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
        lambda: {"employee_pack_tools": tools},
    )
    monkeypatch.setattr(employee_directory, "list_installed_pack_records", lambda: records)


def test_prompt_only_excluded_by_default(monkeypatch):
    _patch(
        monkeypatch,
        [{"pack_id": "wb-expert-demo", "runtime_ok": False, "handlers": []}],
        [{"pack_id": "wb-expert-demo", "manifest": _manifest("wb-expert-demo")}],
    )
    assert employee_directory.build_employee_directory() == []


def test_prompt_only_included_for_display(monkeypatch):
    _patch(
        monkeypatch,
        [{"pack_id": "wb-expert-demo", "runtime_ok": False, "handlers": []}],
        [{"pack_id": "wb-expert-demo", "manifest": _manifest("wb-expert-demo")}],
    )
    rows = employee_directory.build_employee_directory(include_prompt_only=True)
    assert len(rows) == 1
    row = rows[0]
    assert row["pack_id"] == "wb-expert-demo"
    assert row["prompt_only"] is True
    assert row["runtime_ok"] is False
    assert row["runtime_kind"] == "prompt_only"
    assert row["label"] == "对话型专家"
    assert row["area"] == "craft-workshop"


def test_broken_direct_python_pack_stays_hidden(monkeypatch):
    _patch(
        monkeypatch,
        [{"pack_id": "broken-pack", "runtime_ok": False, "handlers": ["direct_python"]}],
        [{"pack_id": "broken-pack", "manifest": _manifest("broken-pack")}],
    )
    assert employee_directory.build_employee_directory(include_prompt_only=True) == []


def test_prompt_only_requires_explicit_system_prompt(monkeypatch):
    manifest = _manifest("wb-expert-demo")
    manifest["employee_config_v2"]["cognition"]["agent"].pop("system_prompt")
    _patch(
        monkeypatch,
        [{"pack_id": "wb-expert-demo", "runtime_ok": False, "handlers": []}],
        [{"pack_id": "wb-expert-demo", "manifest": manifest}],
    )
    assert employee_directory.build_employee_directory(include_prompt_only=True) == []


def test_directory_preserves_explicit_department_without_reclassifying_by_name(monkeypatch):
    manifest = _manifest("print-support")
    manifest["enterprise_layer"] = "service"
    _patch(
        monkeypatch,
        [{"pack_id": "print-support", "runtime_ok": True, "handlers": ["direct_python"]}],
        [{"pack_id": "print-support", "manifest": manifest}],
    )
    row = employee_directory.build_employee_directory()[0]
    assert row["enterprise_layer"] == "service"
    assert row["area"] == "craft-workshop"
