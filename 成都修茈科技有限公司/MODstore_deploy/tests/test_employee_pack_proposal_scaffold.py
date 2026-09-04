"""Bounded autonomous employee-pack source generation tests."""

from __future__ import annotations

import asyncio
import importlib.util
import json

import pytest

from modstore_server.employee_pack_proposal import _call_llm, propose_employee_pack
from modstore_server.employee_pack_proposal_scaffold import (
    ProposalScaffoldError,
    build_source_files,
    materialize_proposal,
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
                    {
                        "message": {
                            "content": 'proposal follows: {"proposal_id":"clean-ci"}'
                        }
                    }
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
    assert (
        manifest["employee_config_v2"]["collaboration"]["workflow"]["workflow_id"] == 0
    )

    result = materialize_proposal(proposal, repo_root=tmp_path)
    source_dir = tmp_path / result["source_dir"]
    assert result["file_count"] == 5
    assert sorted(
        path.relative_to(source_dir).as_posix()
        for path in source_dir.rglob("*")
        if path.is_file()
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
            "recommendation": (
                "Close gate customer_value with immutable evidence: paid_invoice"
            ),
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
