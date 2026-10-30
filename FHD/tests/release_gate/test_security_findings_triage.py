from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "security" / "triage_security_findings.py"


def _mod():
    spec = importlib.util.spec_from_file_location("triage_security_findings", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_dedupes_duplicate_high_findings_but_does_not_clear_gate(tmp_path):
    mod = _mod()
    report = {
        "available": True,
        "findings": [
            {"id": "x1", "severity": "high", "status": "open", "rule_id": "R1", "path": "a.py"},
            {"id": "x1", "severity": "high", "status": "open", "rule_id": "R1", "path": "a.py"},
            {"id": "c1", "severity": "critical", "status": "open", "rule_id": "C1", "path": "b.py"},
            {"id": "m1", "severity": "medium", "status": "open", "rule_id": "M1", "path": "c.py"},
        ],
    }
    (tmp_path / "trivy-filesystem.json").write_text(json.dumps(report))
    result = mod.triage(tmp_path)
    assert result["raw_blocking_count"] == 3
    assert result["unique_blocking_count"] == 2
    assert result["unique_by_severity"] == {"high": 1, "critical": 1}
    assert result["rubber_stamp_forbidden"] is True
    assert result["gate_still_fail_closed"] is True


def test_no_blocking_findings_exits_zero(tmp_path, monkeypatch):
    mod = _mod()
    (tmp_path / "gitleaks.json").write_text(json.dumps({"available": True, "findings": []}))
    monkeypatch.setattr(
        mod.sys,
        "argv",
        ["triage_security_findings.py", "--reports-dir", str(tmp_path)],
    )
    assert mod.main() == 0
