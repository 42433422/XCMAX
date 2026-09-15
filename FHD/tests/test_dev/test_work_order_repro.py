"""连接件3（自动复现）测试：诊断 → 复现场景 → 红/绿证据。

覆盖：
- 目标文件在仓库内 → 生成 module_import 复现用例（status=generated）
- 目标文件不在仓库 → 仅规格（status=needs_scenario，不造假自动复现）
- --run 执行：可导入模块 → reproduced=False（GREEN）；故障模块 → reproduced=True（RED）
- 中继链：_ensure_diagnoses 后自动产出复现规格
- issue 正文嵌入自动复现节
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from app.services import capability_proposal_recorder as recorder

_FHD_ROOT = Path(__file__).resolve().parents[2]

_DIAGNOSE_PATH = _FHD_ROOT / "scripts/dev/work_order_diagnose.py"
_REPRO_PATH = _FHD_ROOT / "scripts/dev/work_order_repro.py"
_TO_ISSUE_PATH = _FHD_ROOT / "scripts/dev/capability_proposal_to_issue.py"


def _load_script(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


repro = _load_script(_REPRO_PATH, "work_order_repro")
to_issue = _load_script(_TO_ISSUE_PATH, "capability_proposal_to_issue")


def _diagnosis(tmp_path: Path, file_path: str) -> dict[str, Any]:
    return {
        "dedup_key": "deadbeef" * 8,
        "wo_id": "WO-test",
        "engine": "rule",
        "errors": [
            {
                "tool": "ruff",
                "code": "F401",
                "message": "`os` imported but unused",
                "file_path": file_path,
                "line": 3,
                "raw": "",
            }
        ],
        "fixes": [{"description": "remove unused import", "needs_human": False}],
        "evidence": {"path": str(tmp_path / "b.zip"), "intact": True},
    }


class TestGenerateRepro:
    def test_module_import_generated(self, tmp_path: Path) -> None:
        out = tmp_path / "repro"
        repro._REPRO_DIR = out
        spec = repro.generate_repro(_diagnosis(tmp_path, "app/services/work_order_state.py"))
        assert spec is not None
        assert spec["kind"] == "module_import"
        assert spec["status"] == "generated"
        assert spec["scenario"]["module"] == "app.services.work_order_state"
        test_path = Path(spec["scenario"]["test_path"])
        assert test_path.is_file()
        assert "app.services.work_order_state" in test_path.read_text(encoding="utf-8")

    def test_missing_target_needs_scenario(self, tmp_path: Path) -> None:
        out = tmp_path / "repro"
        repro._REPRO_DIR = out
        spec = repro.generate_repro(_diagnosis(tmp_path, "app/nope/ghost_file.py"))
        assert spec is not None
        assert spec["kind"] == "none"
        assert spec["status"] == "needs_scenario"
        assert spec["scenario"] is None

    def test_non_python_signature_needs_scenario(self, tmp_path: Path) -> None:
        out = tmp_path / "repro"
        repro._REPRO_DIR = out
        diagnosis = _diagnosis(tmp_path, "")
        diagnosis["errors"] = []
        spec = repro.generate_repro(diagnosis)
        assert spec is not None
        assert spec["status"] == "needs_scenario"


class TestRunRepro:
    def test_green_when_module_importable(self, tmp_path: Path) -> None:
        spec = _diagnosis(tmp_path, "app/services/work_order_state.py")
        spec["kind"] = "module_import"
        spec["scenario"] = {"module": "app.services.work_order_state"}
        out = tmp_path / "repro"
        out.mkdir()
        repro._REPRO_DIR = out
        generated = repro.generate_repro(spec)
        assert generated is not None
        evidence = repro.run_repro(generated)
        assert evidence["reproduced"] is False
        assert evidence["exit_code"] == 0

    def test_red_when_module_missing(self, tmp_path: Path) -> None:
        """故障语义验证：导入失败 → reproduced=True（RED=复现）。"""
        out = tmp_path / "repro"
        out.mkdir()
        test_path = out / "test_repro_red.py"
        test_path.write_text(
            "import importlib\n\n"
            "def test_repro_module_importable() -> None:\n"
            "    try:\n"
            "        importlib.import_module('app.no.such.module')\n"
            "    except Exception as exc:\n"
            "        import pytest\n"
            "        pytest.fail(f'repro: import failed: {exc}')\n",
            encoding="utf-8",
        )
        spec = {
            "dedup_key": "cafebabe" * 8,
            "wo_id": "WO-red",
            "kind": "module_import",
            "scenario": {"module": "app.no.such.module", "test_path": str(test_path)},
        }
        evidence = repro.run_repro(spec)
        assert evidence["reproduced"] is True
        assert evidence["exit_code"] != 0

    def test_no_executable_scenario_skipped(self, tmp_path: Path) -> None:
        spec = {"dedup_key": "a" * 64, "wo_id": "WO-x", "kind": "none", "scenario": None}
        evidence = repro.run_repro(spec)
        assert evidence.get("skipped") == "no_executable_scenario"


class TestRelayChain:
    def test_ensure_diagnoses_also_generates_repro(
        self, isolated_proposals: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        diagnose = _load_script(_DIAGNOSE_PATH, "work_order_diagnose_chain")
        import hashlib
        import zipfile

        zip_path = tmp_path / "b.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "logs/xcagi.log",
                "app/services/work_order_state.py:3:1: F401 [*] `os` imported but unused\n",
            )
        blob = zip_path.read_bytes()
        ref = {
            "kind": "support_bundle",
            "path": str(zip_path),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "bytes": len(blob),
        }
        recorder.record_capability_proposal(
            raw_input="复现链路验证", reason="skill_proposal", evidence_ref=ref
        )
        monkeypatch.setenv("WORK_ORDER_DIAGNOSIS_DIR", str(tmp_path / "diag"))
        monkeypatch.setenv("WORK_ORDER_REPRO_DIR", str(tmp_path / "repro"))
        to_issue._ensure_diagnoses(recorder.list_pending_proposals())
        repro_files = list((tmp_path / "repro").glob("repro-*.json"))
        assert len(repro_files) == 1
        spec = json.loads(repro_files[0].read_text(encoding="utf-8"))
        assert spec["kind"] == "module_import"
        # 中继正文同时嵌入诊断节与复现节
        monkeypatch.setattr(recorder, "_REPORT_DIR", isolated_proposals)
        pending = recorder.list_pending_proposals()
        body = to_issue._build_issue_body(pending[0])
        assert "自动复现" in body
        assert "module_import" in body

    def test_issue_body_without_repro_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORK_ORDER_REPRO_DIR", str(tmp_path / "none"))
        body = to_issue._build_repro_section("ab" * 6)
        assert body == ""


@pytest.fixture
def isolated_proposals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(recorder, "_REPORT_DIR", tmp_path)
    monkeypatch.setattr(recorder, "_PROPOSAL_FILE", tmp_path / "capability_proposal.jsonl")
    monkeypatch.setattr(
        recorder, "_PROCESSED_FILE", tmp_path / "capability_proposal_processed.jsonl"
    )
    from app.services import work_order_ssot as wo

    monkeypatch.setattr(wo, "_STORE_DIR", tmp_path)
    monkeypatch.setattr(wo, "_EVENTS_FILE", tmp_path / "work_orders.jsonl")
    return tmp_path
