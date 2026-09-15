"""连接件2（自动诊断编排）测试：证据包 → 结构化诊断 → 中继写 issue。

覆盖：
- 规则引擎路径：bundle 日志含 ruff F401 → engine=rule 且给出修复建议
- 证据包缺失 / SHA256 不完整场景的 fail-open 行为
- 无 evidence_ref 的提案不进入诊断
- 幂等：已存在诊断文件默认跳过，--force 才重写
- 中继 _build_issue_body 在诊断文件存在时嵌入「自动诊断」节
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from app.services import capability_proposal_recorder as recorder

_FHD_ROOT = Path(__file__).resolve().parents[2]


def _load_script(relpath: str, name: str) -> Any:
    path = _FHD_ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


diagnose = _load_script("scripts/dev/work_order_diagnose.py", "work_order_diagnose")
to_issue = _load_script("scripts/dev/capability_proposal_to_issue.py", "capability_proposal_to_issue")


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


def _make_bundle(tmp_path: Path, log_text: str) -> dict[str, Any]:
    zip_path = tmp_path / "support-bundle-test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("logs/xcagi.log", log_text)
    blob = zip_path.read_bytes()
    return {
        "kind": "support_bundle",
        "path": str(zip_path),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "bytes": len(blob),
        "generated_at": "20260915T000000-00000",
    }


def _proposal_with_evidence(raw_input: str, ref: dict[str, Any]) -> dict[str, Any]:
    result = recorder.record_capability_proposal(
        raw_input=raw_input, reason="skill_proposal", evidence_ref=ref
    )
    assert result["recorded"] is True
    return result


class TestDiagnoseProposal:
    def test_rule_engine_diagnosis(self, isolated_proposals: Path, tmp_path: Path) -> None:
        ref = _make_bundle(
            tmp_path, "app/foo.py:3:1: F401 [*] `os` imported but unused\n"
        )
        _proposal_with_evidence("日志里看到导入未使用", ref)
        out_dir = tmp_path / "diagnosis"
        rc = diagnose.main(["--out-dir", str(out_dir)])
        assert rc == 0
        files = list(out_dir.glob("diagnosis-*.json"))
        assert len(files) == 1
        record = json.loads(files[0].read_text(encoding="utf-8"))
        assert record["engine"] == "rule"
        assert record["evidence"]["intact"] is True
        assert record["fixes"], "ruff F401 规则应产出修复建议"
        assert record["fixes"][0]["tool"] == "ruff"

    def test_evidence_missing_fail_open(
        self, isolated_proposals: Path, tmp_path: Path
    ) -> None:
        ref = {
            "kind": "support_bundle",
            "path": str(tmp_path / "missing.zip"),
            "sha256": "",
            "bytes": 0,
        }
        _proposal_with_evidence("证据包被清理", ref)
        out_dir = tmp_path / "diagnosis"
        assert diagnose.main(["--out-dir", str(out_dir)]) == 0
        files = list(out_dir.glob("diagnosis-*.json"))
        assert len(files) == 1
        record = json.loads(files[0].read_text(encoding="utf-8"))
        assert record["status"] == "evidence_missing"

    def test_no_evidence_ref_skipped(self, isolated_proposals: Path, tmp_path: Path) -> None:
        recorder.record_capability_proposal(raw_input="普通能力提案", reason="skill_proposal")
        out_dir = tmp_path / "diagnosis"
        assert diagnose.main(["--out-dir", str(out_dir)]) == 0
        assert not out_dir.exists()

    def test_idempotent_skip_and_force(self, isolated_proposals: Path, tmp_path: Path) -> None:
        ref = _make_bundle(tmp_path, "app/foo.py:3:1: F401 [*] `os` imported but unused\n")
        _proposal_with_evidence("重复诊断幂等", ref)
        out_dir = tmp_path / "diagnosis"
        assert diagnose.main(["--out-dir", str(out_dir)]) == 0
        files = list(out_dir.glob("diagnosis-*.json"))
        assert len(files) == 1
        body_first = files[0].read_text(encoding="utf-8")
        assert diagnose.main(["--out-dir", str(out_dir)]) == 0
        assert files[0].read_text(encoding="utf-8") == body_first, "默认应跳过已存在诊断文件"
        # --force 重写后内容一致但确实再次执行（时间戳字段刷新）
        assert diagnose.main(["--out-dir", str(out_dir), "--force"]) == 0
        record = json.loads(files[0].read_text(encoding="utf-8"))
        assert record["engine"] == "rule"


class TestRelayEmbedding:
    def test_ensure_diagnoses_produces_file(
        self, isolated_proposals: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """连接件2接线：中继建单前自动为带证据引用的提案产出诊断文件。"""
        ref = _make_bundle(tmp_path, "app/foo.py:3:1: F401 [*] `os` imported but unused\n")
        _proposal_with_evidence("中继自动诊断", ref)
        monkeypatch.setenv("WORK_ORDER_DIAGNOSIS_DIR", str(tmp_path / "diag-auto"))
        to_issue._ensure_diagnoses(recorder.list_pending_proposals())
        produced = list((tmp_path / "diag-auto").glob("diagnosis-*.json"))
        assert len(produced) == 1
        record = json.loads(produced[0].read_text(encoding="utf-8"))
        assert record["engine"] == "rule"

    def test_ensure_diagnoses_noop_without_evidence(
        self, isolated_proposals: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder.record_capability_proposal(raw_input="无证据提案", reason="skill_proposal")
        monkeypatch.setenv("WORK_ORDER_DIAGNOSIS_DIR", str(tmp_path / "diag-none"))
        to_issue._ensure_diagnoses(recorder.list_pending_proposals())
        assert not (tmp_path / "diag-none").exists()

    def test_issue_body_embeds_diagnosis_section(
        self, isolated_proposals: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ref = _make_bundle(tmp_path, "app/foo.py:3:1: F401 [*] `os` imported but unused\n")
        result = _proposal_with_evidence("模板导入报错", ref)
        out_dir = tmp_path / "diagnosis"
        assert diagnose.main(["--out-dir", str(out_dir)]) == 0
        monkeypatch.setenv("WORK_ORDER_DIAGNOSIS_DIR", str(out_dir))
        pending = recorder.list_pending_proposals()
        proposal = next(p for p in pending if p["dedup_key"] == result["dedup_key"])
        body = to_issue._build_issue_body(proposal)
        assert "自动诊断" in body
        assert "诊断引擎" in body
        assert "F401" in body
        # 治理门禁：用户原文不得进入 issue
        assert "模板导入报错" not in body

    def test_issue_body_without_diagnosis_file_is_unchanged(
        self, isolated_proposals: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WORK_ORDER_DIAGNOSIS_DIR", str(tmp_path / "nonexistent"))
        recorder.record_capability_proposal(raw_input="无诊断提案", reason="skill_proposal")
        pending = recorder.list_pending_proposals()
        body = to_issue._build_issue_body(pending[0])
        assert "自动诊断" not in body
