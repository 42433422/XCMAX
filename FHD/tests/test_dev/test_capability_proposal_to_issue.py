"""能力提案中继的隐私、治理和幂等契约。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.services import capability_proposal_recorder as recorder

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "dev" / "capability_proposal_to_issue.py"
)
_spec = importlib.util.spec_from_file_location("capability_proposal_to_issue", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
relay = importlib.util.module_from_spec(_spec)
sys.modules["capability_proposal_to_issue"] = relay
_spec.loader.exec_module(relay)


def test_ci_workflow_is_manual_fallback_not_false_local_scheduler() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    for path in (
        repo_root / "FHD" / ".github" / "workflows" / "capability-proposal-to-issue.yml",
        repo_root / ".github" / "workflows" / "fhd-capability-proposal-to-issue.yml",
    ):
        workflow = path.read_text(encoding="utf-8")
        assert "workflow_dispatch:" in workflow
        assert "schedule:" not in workflow
        assert "capability_proposal_relay" in workflow


@pytest.fixture
def proposal_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    recorder._REPORT_DIR = tmp_path
    recorder._PROPOSAL_FILE = tmp_path / "capability_proposal.jsonl"
    recorder._PROCESSED_FILE = tmp_path / "capability_proposal_processed.jsonl"
    monkeypatch.setattr(relay, "list_pending_proposals", recorder.list_pending_proposals)
    monkeypatch.setattr(relay, "mark_proposals_processed", recorder.mark_proposals_processed)
    return tmp_path


def _actionable(raw_input: str = "生成供应商风险报告") -> dict:
    return {
        "ts": "2026-08-01T00:00:00+00:00",
        "ts_unix": 1.0,
        "source": "intent_confirmation_service",
        "reason": "skill_proposal",
        "raw_input": raw_input,
        "dedup_key": "sample",
        "context": {
            "intent_result": {"slot_names": ["contact_phone"]},
            "skill_proposal": {
                "proposed_skill_id": "open.vendor_risk_report",
                "title": f"开放技能：{raw_input}",
                "candidate_slots": ["unit_name"],
                "rationale": "classifier_miss_or_low_confidence",
                "status": "proposed",
            },
        },
    }


def test_issue_body_and_title_do_not_expose_raw_input() -> None:
    proposal = _actionable("联系人 13800000000 要供应商风险报告")
    proposal["context"]["intent_result"]["primary_intent"] = "客户 13800000000"
    proposal["context"]["skill_proposal"]["candidate_slots"] = [
        "unit_name",
        "客户 13800000000",
    ]
    proposal["context"]["skill_proposal"]["rationale"] = "电话 13800000000"
    body = relay._build_issue_body(proposal)
    title = relay._build_issue_title(proposal)

    assert "13800000000" not in body
    assert "13800000000" not in title
    assert "sample" in body
    assert "slot_names" in body


def test_only_structured_skill_proposal_is_actionable() -> None:
    assert relay._is_actionable_skill_proposal(_actionable()) is True
    legacy = _actionable()
    legacy["reason"] = "intent_unknown"
    assert relay._is_actionable_skill_proposal(legacy) is False
    malformed = _actionable()
    malformed["context"] = {}
    assert relay._is_actionable_skill_proposal(malformed) is False


def test_apply_ignores_legacy_and_writes_issue_receipt(
    proposal_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = _actionable("已有技能缺参数")
    legacy["reason"] = "intent_unknown"
    legacy["dedup_key"] = "legacy-key"
    actionable = _actionable("含隐私的真实新能力 13800000000")
    recorder._PROPOSAL_FILE.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in (legacy, actionable)) + "\n",
        encoding="utf-8",
    )
    sent: list[dict] = []

    def fake_post(_url: str, _token: str, payload: dict) -> dict:
        sent.append(payload)
        return {"number": 7, "html_url": "https://github.com/acme/repo/issues/7"}

    monkeypatch.setattr(relay, "_gh_post", fake_post)
    monkeypatch.setattr(relay, "_gh_api_find_existing", lambda *_args: {})
    args = argparse.Namespace(
        repo="acme/repo",
        token="token",
        max_issues=5,
        dry_run=False,
        apply=True,
        gh_cli=False,
    )

    assert relay.run(args) == 0
    assert len(sent) == 1
    assert sent[0]["labels"] == ["capability-proposal", "auto-generated", "needs-human"]
    assert "13800000000" not in sent[0]["body"]
    assert recorder.list_pending_proposals() == []
    receipts = [
        json.loads(line)
        for line in recorder._PROCESSED_FILE.read_text(encoding="utf-8").splitlines()
    ]
    assert {row["disposition"] for row in receipts} == {
        "ignored_non_skill_proposal",
        "issue_created",
    }


def test_existing_remote_issue_is_reconciled_without_duplicate(
    proposal_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder._PROPOSAL_FILE.write_text(
        json.dumps(_actionable(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        relay,
        "_gh_api_find_existing",
        lambda *_args: {"html_url": "https://github.com/acme/repo/issues/7"},
    )
    post_calls: list[object] = []
    monkeypatch.setattr(relay, "_gh_post", lambda *args: post_calls.append(args))
    args = argparse.Namespace(
        repo="acme/repo",
        token="token",
        max_issues=5,
        dry_run=False,
        apply=True,
        gh_cli=False,
    )

    assert relay.run(args) == 0
    assert post_calls == []
    receipt = json.loads(recorder._PROCESSED_FILE.read_text(encoding="utf-8"))
    assert receipt["disposition"] == "issue_reconciled"
    assert recorder.list_pending_proposals() == []
