"""code-validator 四阶段校验报告（skill-code-validation）。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


def _minimal_employee_pack(
    tmp_path: Path, *, pack_id: str = "test-pack", depends_on: list[str] | None = None
) -> Path:
    pack = tmp_path / pack_id
    (pack / "backend" / "employees").mkdir(parents=True)
    (pack / "skills").mkdir(parents=True)
    deps = depends_on or []
    manifest = {
        "id": pack_id,
        "name": "Test",
        "version": "1.0.0",
        "artifact": "employee_pack",
        "employee": {"id": pack_id, "label": "Test"},
        "depends_on": deps,
        "employee_config_v2": {
            "identity": {"id": pack_id, "owner": "admin", "area": "craft-workshop"},
            "cognition": {
                "skills": [{"name": "skill-test", "path": "skills/skill-test.md"}],
            },
            "actions": {"handlers": ["echo"]},
            "collaboration": {"depends_on": deps},
            "workspace_policy": {
                "scope_globs": ["workbench/sessions/*"],
                "forbidden_globs": ["*.py"],
            },
        },
        "backend": {"entry": "blueprints", "init": "mod_init"},
    }
    (pack / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (pack / "skills" / "skill-test.md").write_text("# skill\n", encoding="utf-8")
    (pack / "backend" / "employees" / "test_pack.py").write_text(
        "async def run(payload, ctx):\n    return {'ok': True, 'summary': '', 'error': ''}\n",
        encoding="utf-8",
    )
    (pack / "backend" / "blueprints.py").write_text("# stub\n", encoding="utf-8")
    return pack


def test_missing_pack_dir_fails_fast():
    from modstore_server.mod_scaffold_runner import run_employee_pack_code_validation_report

    report = asyncio.run(
        run_employee_pack_code_validation_report(Path("/nonexistent/pack-dir-xyz")),
    )
    assert report["status"] == "fail"
    assert report["manifest_validation"]["status"] == "fail"
    assert "不存在" in report["summary"] or "不可读" in report["summary"]
    assert report["python_compile"]["status"] == "skipped"


def test_missing_depends_on_fails_consistency(tmp_path):
    from modstore_server.mod_scaffold_runner import run_employee_pack_code_validation_report

    pack = _minimal_employee_pack(tmp_path, depends_on=["not-a-real-employee-id-xyz"])
    report = asyncio.run(run_employee_pack_code_validation_report(pack))
    assert report["consistency_check"]["status"] == "fail"
    assert "not-a-real-employee-id-xyz" in report["consistency_check"]["missing_depends"]
    assert report["status"] == "fail"


def test_registered_depends_on_passes_consistency(tmp_path, monkeypatch):
    from modstore_server import mod_scaffold_runner as msr

    pack = _minimal_employee_pack(tmp_path, depends_on=["sandbox-tester"])
    monkeypatch.setattr(
        msr,
        "global_registered_employee_ids",
        lambda **_: {"sandbox-tester", pack.name},
    )
    report = asyncio.run(msr.run_employee_pack_code_validation_report(pack))
    assert report["consistency_check"]["missing_depends"] == []


@pytest.mark.asyncio
async def test_xcemp_timeout_sets_escalate(tmp_path, monkeypatch):
    from modstore_server import mod_scaffold_runner as msr

    pack = _minimal_employee_pack(tmp_path)
    monkeypatch.setattr(
        msr,
        "global_registered_employee_ids",
        lambda **_: {pack.name, "sandbox-tester"},
    )

    async def _timeout_stage(*_a, **_k):
        return {
            "status": "fail",
            "errors": ["timeout"],
            "escalate_to_human": True,
            "package_hash": "abc123",
            "timeout_log": "validate 超时",
        }

    monkeypatch.setattr(msr, "_xcemp_validation_stage", _timeout_stage)
    monkeypatch.setattr(
        "modstore_server.craft_failure_signals._employee_escalate_to_human",
        lambda _e: True,
    )
    report = await msr.run_employee_pack_code_validation_report(pack, xcemp_timeout_seconds=0.01)
    assert report["xcemp_validation"]["escalate_to_human"] is True
    assert report["xcemp_validation"]["package_hash"] == "abc123"
