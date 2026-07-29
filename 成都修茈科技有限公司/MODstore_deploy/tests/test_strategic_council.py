from __future__ import annotations

import json

import pytest

from modstore_server import strategic_council as council


def _valid_input() -> dict:
    return {
        "proposal_id": "decision-strategic-council",
        "run_id": "run-strategic-council",
        "package_id": "change-request-auditor",
        "version": "1.1.2",
        "package_sha256": "a" * 64,
        "goal_id": "decision-strategic-council",
        "loop_run_id": "loop-strategic-council",
        "para_task_id": "para-strategic-council",
        "strategy_intent": "Implement the strategic council review gate",
        "changed_files": ["modstore_server/strategic_council.py"],
        "persy_evidence": {
            "grounded": True,
            "dataset_id": "persy-knowledge",
            "source_count": 1,
            "document_refs": ["founder-autonomy-policy"],
        },
        "para_evidence": {
            "linked": True,
            "source_verified": True,
            "goal_id": "decision-strategic-council",
            "loop_run_id": "loop-strategic-council",
            "para_task_id": "para-strategic-council",
            "goal_status": "approved",
            "loop_status": "in_progress",
            "task_status": "running",
            "source": "test-authoritative-ledger",
        },
        "veto_state": {
            "available": True,
            "vetoed": False,
            "pending_count": 0,
            "source": "test-redline-channel",
        },
    }


@pytest.fixture(autouse=True)
def _disable_retort_clarification_gate(monkeypatch, tmp_path) -> None:
    """Keep legacy council contract tests deterministic; clarification covered separately."""

    monkeypatch.setenv("MODSTORE_RETORT_CLARIFICATION_ENABLED", "0")
    monkeypatch.setenv(
        "MODSTORE_RETORT_CLARIFICATION_LEDGER",
        str(tmp_path / "retort_clarifications.json"),
    )


def test_verified_receipt_is_hash_chained_and_idempotent(tmp_path, monkeypatch) -> None:
    ledger = tmp_path / "council.jsonl"
    monkeypatch.setenv("MODSTORE_STRATEGIC_COUNCIL_LEDGER", str(ledger))

    first = council.build_strategic_council_receipt(**_valid_input())
    second = council.build_strategic_council_receipt(**_valid_input())
    status = council.strategic_council_status()

    assert first["verified"] is True
    assert first["roles"]["persy"]["status"] == "grounded"
    assert first["roles"]["para"]["status"] == "linked"
    assert first["roles"]["retort"] == {
        **first["roles"]["retort"],
        "status": "aligned",
        "engine_available": True,
    }
    assert second["receipt_id"] == first["receipt_id"]
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1
    assert status["ready"] is True
    assert status["hash_chain_verified"] is True
    assert status["verified_receipt_count"] == 1
    assert status["latest_receipt"]["goal_id"] == "decision-strategic-council"


@pytest.mark.parametrize(
    ("section", "updates", "blocker"),
    [
        (
            "persy_evidence",
            {"grounded": False, "source_count": 0},
            "persy_grounding_missing",
        ),
        ("para_evidence", {"source_verified": False}, "para_source_unverified"),
        ("veto_state", {"vetoed": True}, "veto_active"),
        ("veto_state", {"pending_count": 1}, "veto_pending"),
    ],
)
def test_missing_evidence_or_veto_fails_closed(
    tmp_path, monkeypatch, section: str, updates: dict, blocker: str
) -> None:
    monkeypatch.setenv("MODSTORE_STRATEGIC_COUNCIL_LEDGER", str(tmp_path / "council.jsonl"))
    payload = _valid_input()
    payload[section] = {**payload[section], **updates}

    receipt = council.build_strategic_council_receipt(**payload)
    status = council.strategic_council_status()

    assert receipt["verified"] is False
    assert blocker in receipt["blockers"]
    assert status["ready"] is False
    assert status["verified_receipt_count"] == 0
    assert status["attempt_count"] == 1


def test_retort_engine_unavailable_fails_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_STRATEGIC_COUNCIL_LEDGER", str(tmp_path / "council.jsonl"))

    def unavailable():
        raise ImportError("retort missing")

    monkeypatch.setattr(council, "_load_retort_alignment", unavailable)
    receipt = council.build_strategic_council_receipt(**_valid_input())

    assert receipt["verified"] is False
    assert "retort_engine_unavailable" in receipt["blockers"]
    assert receipt["roles"]["retort"]["engine_available"] is False


def test_live_persy_evidence_uses_only_the_public_persy_dataset(monkeypatch) -> None:
    from modstore_server import xiaoc_cs_ssot

    monkeypatch.setattr(
        xiaoc_cs_ssot,
        "retrieve_knowledge_for_mode",
        lambda *_args, **_kwargs: pytest.fail("admin multi-dataset retrieval must not be used"),
    )
    monkeypatch.setattr(
        xiaoc_cs_ssot,
        "retrieve_persy_knowledge",
        lambda query, *, top_k: [
            {
                "document_id": "founder-policy",
                "dataset_id": "persy-knowledge",
                "text": f"{query}:{top_k}",
            }
        ],
    )

    evidence = council._live_persy_evidence("无人公司治理边界")

    assert evidence["grounded"] is True
    assert evidence["dataset_id"] == "persy-knowledge"
    assert evidence["document_refs"] == ["founder-policy"]
    assert evidence["source_count"] == 1


def test_tampered_ledger_never_reports_ready(tmp_path, monkeypatch) -> None:
    ledger = tmp_path / "council.jsonl"
    monkeypatch.setenv("MODSTORE_STRATEGIC_COUNCIL_LEDGER", str(ledger))
    council.build_strategic_council_receipt(**_valid_input())
    row = json.loads(ledger.read_text(encoding="utf-8"))
    row["goal_id"] = "tampered"
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")

    status = council.strategic_council_status()

    assert status["ok"] is False
    assert status["ready"] is False
    assert status["hash_chain_verified"] is False
    assert status["verified_receipt_count"] == 0


def test_live_builder_uses_runtime_evidence_resolvers(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_STRATEGIC_COUNCIL_LEDGER", str(tmp_path / "council.jsonl"))
    payload = _valid_input()
    payload.pop("persy_evidence")
    payload.pop("para_evidence")
    payload.pop("veto_state")
    monkeypatch.setattr(
        council,
        "_live_persy_evidence",
        lambda _intent: _valid_input()["persy_evidence"],
    )
    monkeypatch.setattr(
        council,
        "_live_para_evidence",
        lambda **_kwargs: _valid_input()["para_evidence"],
    )
    monkeypatch.setattr(
        council,
        "_live_veto_state",
        lambda **_kwargs: _valid_input()["veto_state"],
    )

    receipt = council.build_live_strategic_council_receipt(**payload)

    assert receipt["verified"] is True
