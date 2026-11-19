"""Bounded autonomous employee-pack source generation tests."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from modstore_server.employee_pack_proposal import (
    PROPOSAL_SOURCES,
    ProposalValidationError,
    _call_llm,
    propose_employee_pack,
)
from modstore_server.employee_pack_proposal_scaffold import (
    ProposalScaffoldError,
    build_source_files,
    main,
    materialize_proposal,
    unsupported_proposal_reason,
)


def _signals() -> dict:
    return {
        "catalog_capability_gap": {
            "signal_score": 1.0,
            "report": {
                "package_id": "autonomy-gap-analyst",
                "version": "1.0.0",
            },
        },
        "legacy_usage": {"signal_score": 0.0},
        "intent_benchmark": {"signal_score": 0.0},
        "slo_metrics": {"signal_score": 0.0},
        "signals_to_propose": 1,
    }


def test_catalog_gap_has_safe_fallback_when_llm_unavailable():
    proposal = propose_employee_pack(_signals(), llm_call=lambda _prompt: {})
    assert proposal is not None
    assert proposal["triggered_by"] == "catalog_capability_gap"
    assert proposal["employee_pack"]["name"] == "autonomy-gap-analyst"
    assert proposal["estimated_files"] == 5
    assert "customer payment" in proposal["employee_pack"]["prompt_template"]


def test_clean_ci_llm_client_parses_openai_json(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_API_KEY", "test-key")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("XCAGI_LLM_MODEL", "test-model")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {"message": {"content": 'proposal follows: {"proposal_id":"clean-ci"}'}}
                ]
            }

    calls = []

    def fake_post(endpoint, **kwargs):
        calls.append((endpoint, kwargs))
        return Response()

    monkeypatch.setattr("httpx.post", fake_post)
    assert _call_llm("design") == {"proposal_id": "clean-ci"}
    assert calls[0][0] == "https://llm.example/v1/chat/completions"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-key"


def test_scaffold_is_exactly_three_installable_source_files(tmp_path):
    proposal = propose_employee_pack(_signals(), llm_call=lambda _prompt: {})
    files = build_source_files(proposal)
    assert set(files) == {
        "manifest.json",
        "prompt.txt",
        "skills.json",
        "backend/employees/autonomy_gap_analyst.py",
        "backend/vendor/autonomy_gap_analyst/convert.py",
    }
    manifest = json.loads(files["manifest.json"])
    assert manifest["artifact"] == "employee_pack"
    assert manifest["employee_config_v2"]["actions"]["handlers"] == ["direct_python"]
    assert manifest["employee_config_v2"]["collaboration"]["workflow"]["workflow_id"] == 0

    result = materialize_proposal(proposal, repo_root=tmp_path)
    source_dir = tmp_path / result["source_dir"]
    assert result["file_count"] == 5
    assert sorted(
        path.relative_to(source_dir).as_posix() for path in source_dir.rglob("*") if path.is_file()
    ) == [
        "backend/employees/autonomy_gap_analyst.py",
        "backend/vendor/autonomy_gap_analyst/convert.py",
        "manifest.json",
        "prompt.txt",
        "skills.json",
    ]
    module_path = source_dir / "backend/employees/autonomy_gap_analyst.py"
    spec = importlib.util.spec_from_file_location("generated_gap_analyst", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    execution = asyncio.run(
        module.run(
            {
                "scorecard": {
                    "customer_value": {
                        "status": "failed",
                        "required_receipt": "paid_invoice",
                    },
                    "deployment": {"status": "passed"},
                }
            },
            {},
        )
    )
    assert execution["ok"] is True
    assert execution["items"] == [
        {
            "gate": "customer_value",
            "path": "customer_value",
            "status": "failed",
            "missing_receipt": "paid_invoice",
            "recommendation": ("Close gate customer_value with immutable evidence: paid_invoice"),
        }
    ]
    with pytest.raises(ProposalScaffoldError, match="already exists"):
        materialize_proposal(proposal, repo_root=tmp_path)


def test_llm_cannot_redirect_catalog_gap_package_identity():
    proposal = propose_employee_pack(
        _signals(),
        llm_call=lambda _prompt: {
            "proposal_id": "llm-proposal",
            "department": "quality",
            "employee_pack": {
                "name": "../../unsafe",
                "responsibility": "Analyze evidence.",
                "prompt_template": "Analyze only supplied evidence.",
                "skills": ["evidence-analysis"],
                "tools": ["shell"],
                "acceptance_criteria": ["cite the missing receipt"],
            },
            "estimated_files": 5,
            "estimated_tokens": 20000,
        },
    )
    assert proposal["employee_pack"]["name"] == "autonomy-gap-analyst"
    assert proposal["estimated_files"] == 5


def test_direct_caller_cannot_materialize_unreviewed_package_identity():
    proposal = propose_employee_pack(_signals(), llm_call=lambda _prompt: {})
    proposal["employee_pack"]["name"] = "another-safe-looking-pack"

    with pytest.raises(ProposalScaffoldError, match="not allowlisted"):
        build_source_files(proposal)


def test_scaffold_classification_does_not_turn_invalid_schema_into_manual_deferral():
    proposal = propose_employee_pack(_signals(), llm_call=lambda _prompt: {})
    proposal["triggered_by"] = "slo_metrics"
    proposal["employee_pack"]["skills"] = "invalid"
    with pytest.raises(ProposalValidationError, match="skills must be list"):
        unsupported_proposal_reason(proposal)


@pytest.mark.parametrize("destination", ["missing-temp", "outside", "nested", "relative"])
def test_scaffold_receipt_requires_trusted_runner_temp(tmp_path, monkeypatch, destination):
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    receipt = runner_temp / "receipt.json"
    if destination == "missing-temp":
        monkeypatch.delenv("RUNNER_TEMP")
    elif destination == "outside":
        receipt = tmp_path / "receipt.json"
    elif destination == "nested":
        receipt = runner_temp / "nested" / "receipt.json"
    else:
        receipt = Path("receipt.json")
    monkeypatch.setattr(
        "sys.argv",
        [
            "scaffold",
            "--proposal-file",
            str(tmp_path / "never-read.json"),
            "--repo-root",
            str(tmp_path),
            "--result-file",
            str(receipt),
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 2
    assert not receipt.exists()
    assert list(tmp_path.iterdir()) == [runner_temp]


@pytest.mark.parametrize("failure", ["stale", "symlink", "invalid-version"])
def test_scaffold_cli_receipt_failure_leaves_source_untouched(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    receipt = tmp_path / "receipt.json"
    proposal = propose_employee_pack(_signals(), llm_call=lambda _prompt: {})
    if failure == "invalid-version":
        proposal["target_version"] = "../../escape"
    elif failure == "stale":
        receipt.write_text("original")
    else:
        target = tmp_path / "original"
        target.write_text("original")
        receipt.symlink_to(target)
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps(proposal))
    source_root = tmp_path / "checkout"
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "modstore_server.employee_pack_proposal_scaffold",
            "--proposal-file",
            str(proposal_file),
            "--repo-root",
            str(source_root),
            "--result-file",
            str(receipt),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode != 0
    assert not source_root.exists()
    if failure == "invalid-version":
        assert "unsafe package version" in completed.stderr
        assert not receipt.exists()
    else:
        assert "FileExistsError" in completed.stderr
        assert receipt.read_text() == "original"
        assert receipt.is_symlink() is (failure == "symlink")


def test_malformed_llm_catalog_proposal_uses_safe_fallback():
    proposal = propose_employee_pack(
        _signals(),
        llm_call=lambda _prompt: {
            "proposal_id": "incomplete",
            "department": "quality",
            "employee_pack": {"name": "anything"},
        },
    )
    assert proposal["proposal_mode"] == "deterministic_safe_fallback"
    assert proposal["employee_pack"]["name"] == "autonomy-gap-analyst"


def test_llm_private_text_never_materializes_as_source(tmp_path):
    private_marker = "customer-secret-do-not-persist"
    proposal = propose_employee_pack(
        _signals(),
        llm_call=lambda _prompt: {
            "proposal_id": "llm-private-proposal",
            "department": "quality",
            "employee_pack": {
                "name": "redirected-by-normalizer",
                "responsibility": private_marker,
                "prompt_template": private_marker,
                "skills": [private_marker],
                "tools": ["shell"],
                "acceptance_criteria": [private_marker],
            },
            "estimated_files": 5,
            "estimated_tokens": 1000,
        },
    )

    result = materialize_proposal(proposal, repo_root=tmp_path)

    source_dir = tmp_path / result["source_dir"]
    assert all(
        private_marker not in path.read_text(encoding="utf-8")
        for path in source_dir.rglob("*")
        if path.is_file()
    )


@pytest.mark.parametrize("source", PROPOSAL_SOURCES)
def test_proposal_provenance_is_bound_to_the_selected_signal(source):
    raw = propose_employee_pack(_signals(), llm_call=lambda _prompt: {})
    raw.update(
        triggered_by=(
            "slo_metrics" if source == "catalog_capability_gap" else "catalog_capability_gap"
        ),
        signal_score=-100,
    )
    signals = _signals()
    signals["catalog_capability_gap"]["signal_score"] = 0
    signals[source]["signal_score"] = 0.9

    proposal = propose_employee_pack(signals, llm_call=lambda _prompt: raw)

    assert proposal["triggered_by"] == source
    assert proposal["signal_score"] == 0.9
    if source != "catalog_capability_gap":
        with pytest.raises(ProposalScaffoldError, match="only allowlisted catalog"):
            build_source_files(proposal)


def test_materialized_version_matches_validated_manifest_and_directory(tmp_path):
    proposal = propose_employee_pack(_signals(), llm_call=lambda _prompt: {})
    proposal["target_version"] = " 1.2.3 "

    result = materialize_proposal(proposal, repo_root=tmp_path)

    source = tmp_path / result["source_dir"]
    manifest = json.loads((source / "manifest.json").read_text())
    assert result["version"] == manifest["version"] == "1.2.3"
    assert source.name == "autonomy-gap-analyst@1.2.3"


def test_version_suffix_cannot_hide_beyond_the_validation_limit(tmp_path):
    proposal = propose_employee_pack(_signals(), llm_call=lambda _prompt: {})
    proposal["target_version"] = "1.2." + "3" * 28 + "/unexpected"

    with pytest.raises(ProposalScaffoldError, match="unsafe package version"):
        materialize_proposal(proposal, repo_root=tmp_path)

    assert not list(tmp_path.iterdir())
