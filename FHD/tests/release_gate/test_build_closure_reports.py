from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path


def _module():
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "release"
        / "build_closure_reports.py"
    )
    spec = importlib.util.spec_from_file_location("build_closure_reports", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_four_reports_are_redacted_hashed_and_fail_closed(tmp_path: Path) -> None:
    mod = _module()
    sha = "a" * 40
    release_id = f"xcagi-1.0.0.1-{sha}"
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    convergence = _write(
        inputs / "convergence.json",
        {
            "converged": True,
            "release_sha": sha,
            "release_id": release_id,
            "sources": [{"name": "device-secret", "status": "matched"}],
            "blockers": [],
            "active_purchased_accounts": 3,
            "reported_installations": 6,
        },
    )
    security = _write(
        inputs / "security.json",
        {"passed": True, "release_sha": sha, "blockers": []},
    )
    slo = _write(
        inputs / "slo.json",
        {
            "passed": True,
            "release_id": release_id,
            "continuous_days": 90,
            "day_0": "2026-09-05",
            "day_n": "2026-12-03",
            "chain_tip": "b" * 64,
            "blockers": [],
        },
    )
    rollback = _write(
        inputs / "rollback.json",
        {
            "passed": True,
            "release_sha": sha,
            "server_rto_minutes": 20,
            "server_rpo_minutes": 3,
            "blockers": [],
        },
    )
    customer = _write(
        inputs / "customer.json",
        {
            "value_ledger_ready": True,
            "three_customer_loop_verified": True,
            "complete_customer_count": 3,
            "release_sha": sha,
            "customers": [
                {
                    "customer_alias": "customer-abc",
                    "enterprise_name": "must-not-leak",
                    "order_no": "must-not-leak",
                    "device_id": "must-not-leak",
                    "stages": dict.fromkeys(mod.STAGES, True),
                    "ordered": True,
                    "complete": True,
                    "gaps": [],
                }
            ],
        },
    )
    output = tmp_path / "reports"

    manifest = mod.build_reports(
        convergence_path=convergence,
        security_path=security,
        slo_path=slo,
        rollback_path=rollback,
        customer_path=customer,
        output_dir=output,
        release_sha=sha,
        now=datetime(2026, 12, 3, tzinfo=UTC),
    )

    assert manifest["passed"] is True
    assert [row["file"] for row in manifest["reports"]] == list(mod.REPORT_FILENAMES)
    rendered = "\n".join(path.read_text() for path in output.glob("*.json"))
    assert "must-not-leak" not in rendered
    assert "device-secret" not in rendered
    for row in manifest["reports"]:
        report = output / row["file"]
        assert hashlib.sha256(report.read_bytes()).hexdigest() == row["sha256"]
        assert (output / f"{row['file']}.sha256").is_file()

    _write(security, {"passed": False, "release_sha": sha, "blockers": ["high"]})
    failed = mod.build_reports(
        convergence_path=convergence,
        security_path=security,
        slo_path=slo,
        rollback_path=rollback,
        customer_path=customer,
        output_dir=output,
        release_sha=sha,
    )
    assert failed["passed"] is False
