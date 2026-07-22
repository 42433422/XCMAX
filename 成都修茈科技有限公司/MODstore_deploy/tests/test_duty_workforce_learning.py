import json
from pathlib import Path

from modstore_server.duty_workforce_learning import (
    load_open_workforce_gaps,
    run_duty_workforce_learning,
)
from modstore_server.self_evolution_knowledge import knowledge_inventory


def _row(
    *,
    employee_id: str,
    run_id: str,
    accepted: bool,
    manifest: str,
    contract: str,
    reasons: list[str] | None = None,
) -> dict:
    return {
        "schema": "xcagi.duty_workforce_burnin.audit/v1",
        "recorded_at": f"2026-07-22T12:{run_id[-2:]}:00+00:00",
        "run_id": run_id,
        "employee_id": employee_id,
        "status": "accepted" if accepted else "rejected",
        "receipt_accepted": accepted,
        "manifest_sha256": manifest,
        "contract_sha256": contract,
        "acceptance": {"reasons": reasons or []},
    }


def _write_audit(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_single_failure_is_gap_candidate_not_reusable_knowledge(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    audit = tmp_path / "burnin.jsonl"
    gaps = tmp_path / "gaps.jsonl"
    _write_audit(
        audit,
        [
            _row(
                employee_id="host-checker",
                run_id="run-01",
                accepted=False,
                manifest="a" * 64,
                contract="b" * 64,
                reasons=["programmatic_verification_failed"],
            )
        ],
    )

    result = run_duty_workforce_learning(audit_path=audit, gap_path=gaps)

    assert result["unresolved_employee_count"] == 1
    assert result["gap_candidate_written_count"] == 1
    assert result["remediation_plan_written_count"] == 1
    assert result["knowledge_written_count"] == 0
    open_gap = load_open_workforce_gaps(path=gaps)[0]
    assert open_gap["remediation"]["kind"] == "repair_existing_employee_capability"
    assert open_gap["remediation"]["target_files"] == [
        "FHD/mods/_employees/host-checker/manifest.json",
        "FHD/mods/_employees/host-checker/backend/employees/host_checker.py",
    ]
    assert open_gap["remediation"]["closure_event"] == (
        "later_strict_burnin_receipt_accepted"
    )
    assert open_gap["remediation"]["auto_close"] is False
    assert knowledge_inventory()["total"] == 0


def test_unchanged_contract_failure_then_acceptance_learns_once(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    audit = tmp_path / "burnin.jsonl"
    gaps = tmp_path / "gaps.jsonl"
    rows = [
        _row(
            employee_id="llm-ops-engineer",
            run_id="run-01",
            accepted=False,
            manifest="a" * 64,
            contract="b" * 64,
            reasons=["executor_handler_failed", "no_successful_tool_call"],
        ),
        _row(
            employee_id="llm-ops-engineer",
            run_id="run-02",
            accepted=True,
            manifest="a" * 64,
            contract="b" * 64,
        ),
    ]
    _write_audit(audit, rows)

    first = run_duty_workforce_learning(audit_path=audit, gap_path=gaps)
    second = run_duty_workforce_learning(audit_path=audit, gap_path=gaps)

    assert first["knowledge_written_count"] == 1
    assert first["pattern_counts"] == {"workforce_burnin_cooldown_retry_verified": 1}
    assert second["knowledge_written_count"] == 0
    assert second["knowledge_skipped_existing_count"] == 1
    assert knowledge_inventory()["pattern_count"] == 1


def test_revised_manifest_must_later_pass_before_learning(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    audit = tmp_path / "burnin.jsonl"
    gaps = tmp_path / "gaps.jsonl"
    _write_audit(
        audit,
        [
            _row(
                employee_id="security-secrets-guard",
                run_id="run-01",
                accepted=False,
                manifest="a" * 64,
                contract="b" * 64,
                reasons=["direct_python_output_not_ok"],
            ),
            _row(
                employee_id="security-secrets-guard",
                run_id="run-02",
                accepted=True,
                manifest="c" * 64,
                contract="b" * 64,
            ),
        ],
    )

    result = run_duty_workforce_learning(audit_path=audit, gap_path=gaps)

    assert result["unresolved_employee_count"] == 0
    assert result["knowledge_written_count"] == 1
    assert result["pattern_counts"] == {"workforce_burnin_contract_revision_verified": 1}
    pattern_path = Path(result["knowledge_paths"][0])
    payload = json.loads(pattern_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["verified_by_later_accepted_receipt"] is True
    assert "direct_python_output_not_ok" in payload["metadata"]["failure_reason_codes"]


def test_malformed_summary_and_missing_hash_rows_do_not_create_proof(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    audit = tmp_path / "burnin.jsonl"
    audit.write_text(
        "not-json\n"
        + json.dumps(
            {
                "record_type": "run_summary",
                "run_id": "summary",
                "selected_count": 2,
            }
        )
        + "\n"
        + json.dumps(
            {
                "employee_id": "missing-hash",
                "run_id": "run-01",
                "status": "accepted",
                "receipt_accepted": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_duty_workforce_learning(
        audit_path=audit, gap_path=tmp_path / "gaps.jsonl"
    )

    assert result["audit_row_count"] == 0
    assert result["resolved_pair_count"] == 0
    assert result["knowledge_written_count"] == 0


def test_unrecognized_reason_text_is_not_copied_into_gap_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    audit = tmp_path / "burnin.jsonl"
    gaps = tmp_path / "gaps.jsonl"
    _write_audit(
        audit,
        [
            _row(
                employee_id="host-checker",
                run_id="run-01",
                accepted=False,
                manifest="a" * 64,
                contract="b" * 64,
                reasons=["token=must-not-copy", "programmatic_verification_failed"],
            )
        ],
    )

    run_duty_workforce_learning(audit_path=audit, gap_path=gaps)

    text = gaps.read_text(encoding="utf-8")
    assert "must-not-copy" not in text
    assert "programmatic_verification_failed" in text


def test_later_accepted_receipt_closes_existing_gap(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    audit = tmp_path / "burnin.jsonl"
    gaps = tmp_path / "gaps.jsonl"
    failure = _row(
        employee_id="security-secrets-guard",
        run_id="run-01",
        accepted=False,
        manifest="a" * 64,
        contract="b" * 64,
        reasons=["direct_python_output_not_ok"],
    )
    _write_audit(audit, [failure])
    first = run_duty_workforce_learning(audit_path=audit, gap_path=gaps)
    assert first["open_gap_count"] == 1
    assert first["remediation_plan_written_count"] == 1
    assert len(load_open_workforce_gaps(path=gaps)) == 1

    accepted = _row(
        employee_id="security-secrets-guard",
        run_id="run-02",
        accepted=True,
        manifest="c" * 64,
        contract="b" * 64,
    )
    _write_audit(audit, [failure, accepted])
    second = run_duty_workforce_learning(audit_path=audit, gap_path=gaps)

    assert second["gap_resolution_written_count"] == 1
    assert second["remediation_plan_written_count"] == 0
    assert second["open_gap_count"] == 0
    assert load_open_workforce_gaps(path=gaps) == []
