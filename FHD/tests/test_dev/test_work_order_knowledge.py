"""连接件5（知识回流）测试：三件套沉淀为案例 + 规则检索 + 诊断消费侧。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

_FHD_ROOT = Path(__file__).resolve().parents[2]

KEY = "a" * 64
KEY12 = KEY[:12]


def _load(name: str, rel: str) -> Any:
    path = _FHD_ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


kb = _load("work_order_knowledge_c5", "scripts/dev/work_order_knowledge.py")
diagnose = _load("work_order_diagnose_c5", "scripts/dev/work_order_diagnose.py")
retest_mod = _load("customer_retest_c5", "scripts/dev/customer_retest.py")


@pytest.fixture
def loop_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("WORK_ORDER_DIAGNOSIS_DIR", str(tmp_path / "diagnosis"))
    monkeypatch.setenv("WORK_ORDER_REPRO_DIR", str(tmp_path / "repro"))
    monkeypatch.setenv("WORK_ORDER_RETEST_DIR", str(tmp_path / "retest"))
    monkeypatch.setenv("WORK_ORDER_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    return tmp_path


def _write_artifacts(tmp_path: Path, *, verdict: str = "pass") -> None:
    diag_dir = tmp_path / "diagnosis"
    diag_dir.mkdir(parents=True, exist_ok=True)
    (diag_dir / f"diagnosis-{KEY12}.json").write_text(
        json.dumps(
            {
                "dedup_key": KEY,
                "wo_id": "WO-kbtest",
                "engine": "rule",
                "errors": [
                    {
                        "tool": "ruff",
                        "code": "F401",
                        "message": "`os` imported but unused",
                        "file_path": "app/services/work_order_state.py",
                        "line": 3,
                    }
                ],
                "fixes": [
                    {
                        "description": "remove unused import `os`",
                        "needs_human": False,
                        "risk_level": "r0",
                        "tool": "ruff",
                        "code": "F401",
                        "file": "app/services/work_order_state.py",
                        "line": 3,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    repro_dir = tmp_path / "repro"
    repro_dir.mkdir(parents=True, exist_ok=True)
    (repro_dir / f"repro-{KEY12}.json").write_text(
        json.dumps(
            {
                "dedup_key": KEY,
                "wo_id": "WO-kbtest",
                "kind": "module_import",
                "status": "generated",
                "scenario": {"module": "app.services.work_order_state"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    retest_dir = tmp_path / "retest"
    retest_dir.mkdir(parents=True, exist_ok=True)
    (retest_dir / f"receipt-{KEY12}.json").write_text(
        json.dumps(
            {
                "dedup_key": KEY,
                "wo_id": "WO-kbtest",
                "verdict": verdict,
                "app_version": "1.0.0.4",
                "base_url": "http://127.0.0.1:8787",
                "checks": [{"name": "app_health", "ok": True, "status": 200}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class TestCompose:
    def test_compose_from_three_artifacts(self, loop_dirs: Path) -> None:
        _write_artifacts(loop_dirs)
        case = kb.compose_case(KEY)
        assert case is not None
        assert case["wo_id"] == "WO-kbtest"
        assert case["signature"] == {
            "tool": "ruff",
            "code": "F401",
            "file": "app/services/work_order_state.py",
            "line": 3,
        }
        assert case["fix_description"] == "remove unused import `os`"
        assert case["repro"]["kind"] == "module_import"
        assert case["retest"]["verdict"] == "pass"

    def test_compose_requires_diagnosis(self, loop_dirs: Path) -> None:
        assert kb.compose_case(KEY) is None


class TestUpsertSearch:
    def test_upsert_idempotent_by_dedup_key(self, loop_dirs: Path) -> None:
        case = kb.compose_case(KEY)
        assert case is None  # 尚无诊断
        _write_artifacts(loop_dirs)
        first = kb.compose_case(KEY)
        assert first is not None
        assert kb.upsert_case(first) == 1
        first["fix_description"] = "updated fix"
        assert kb.upsert_case(first) == 1
        cases = kb.load_cases()
        assert len(cases) == 1
        assert cases[0]["fix_description"] == "updated fix"

    def test_search_by_tool_code(self, loop_dirs: Path) -> None:
        _write_artifacts(loop_dirs)
        case = kb.compose_case(KEY)
        assert case is not None
        kb.upsert_case(case)
        hits = kb.search_cases("ruff", "F401")
        assert len(hits) == 1
        assert hits[0]["wo_id"] == "WO-kbtest"
        assert kb.search_cases("mypy", "F401") == []
        assert kb.search_cases("", "") == []


class TestConsumption:
    def test_diagnose_attaches_known_cases(
        self, loop_dirs: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_artifacts(loop_dirs)
        case = kb.compose_case(KEY)
        assert case is not None
        kb.upsert_case(case)
        zip_path = loop_dirs / "b.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "logs/xcagi.log",
                "app/services/work_order_state.py:3:1: F401 [*] `os` imported but unused\n",
            )
        blob = zip_path.read_bytes()
        proposal = {
            "dedup_key": "b" * 64,
            "evidence_ref": {
                "kind": "support_bundle",
                "path": str(zip_path),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "bytes": len(blob),
            },
        }
        record = diagnose.diagnose_proposal(proposal, use_llm=False)
        assert record is not None
        known = record.get("known_cases")
        assert isinstance(known, list) and len(known) == 1
        assert known[0]["wo_id"] == "WO-kbtest"
        assert known[0]["fix_description"] == "remove unused import `os`"


class TestProductionChain:
    def test_retest_pass_records_knowledge(
        self, loop_dirs: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_artifacts(loop_dirs)
        key12 = retest_mod._spec_dedup_key(KEY12)  # 回执里取完整 dedup_key
        assert key12 == KEY
        retest_mod._record_knowledge(KEY12)
        cases = kb.load_cases()
        assert len(cases) == 1
        assert cases[0]["retest"]["verdict"] == "pass"

    def test_record_without_retest_marks_pending(self, loop_dirs: Path) -> None:
        diag_dir = loop_dirs / "diagnosis"
        diag_dir.mkdir(parents=True)
        (diag_dir / f"diagnosis-{KEY12}.json").write_text(
            json.dumps(
                {
                    "dedup_key": KEY,
                    "wo_id": "WO-kbtest",
                    "engine": "no_signature",
                    "errors": [],
                    "fixes": [],
                }
            ),
            encoding="utf-8",
        )
        case = kb.compose_case(KEY)
        assert case is not None
        assert case["retest"]["verdict"] == "pending"
        assert kb.upsert_case(case) == 1

    def test_close_work_order_uses_state_machine(
        self, loop_dirs: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services import work_order_ssot as wo

        calls: list[tuple[str, str]] = []

        def fake_transition(wo_id: str, to_state: str, **_kw: Any) -> dict[str, Any]:
            calls.append((wo_id, to_state))
            return {"ok": True, "wo_id": wo_id, "from": "verifying", "to": to_state}

        monkeypatch.setattr(wo, "record_transition", fake_transition)
        assert kb.close_work_order("WO-kbtest") is True
        assert calls == [("WO-kbtest", "closed")]
