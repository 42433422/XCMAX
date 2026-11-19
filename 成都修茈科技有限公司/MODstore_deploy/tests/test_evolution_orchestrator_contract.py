"""Native workflow routing and bounded scaffold handoff contracts."""

from __future__ import annotations

import json
import os
import runpy
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from modstore_server import employee_pack_proposal, evolution_signal_collector
from modstore_server.evolution_ledger import list_events

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "FHD" / ".github" / "workflows" / "evolution-orchestrator.yml"
PUBLISHED = REPO_ROOT / ".github" / "workflows" / "fhd-evolution-orchestrator.yml"
CI_SOURCE = REPO_ROOT / "FHD" / ".github" / "workflows" / "ci-cd.yml"
MOD_ROOT = Path(__file__).resolve().parents[1]


def _steps():
    return {
        step.get("id") or step.get("name"): step
        for step in yaml.safe_load(SOURCE.read_text(encoding="utf-8"))["jobs"]["scan-and-propose"][
            "steps"
        ]
    }


def _proposal(source="catalog_capability_gap", name="autonomy-gap-analyst"):
    return {
        "proposal_id": "routing-regression",
        "triggered_by": source,
        "department": "ops",
        "estimated_files": 5,
        "estimated_tokens": 1000,
        "employee_pack": {
            "name": name,
            "prompt_template": "private-proposal-text-must-not-reach-source-or-receipt",
            "skills": [],
            "tools": [],
            "acceptance_criteria": [],
        },
    }


@pytest.mark.parametrize(
    "source,name,allowed",
    [
        ("slo_metrics", "slo-coverage-auditor", False),
        ("catalog_capability_gap", "autonomy-gap-analyst", True),
        ("catalog_capability_gap", "other-pack", False),
        ("slo_metrics", "autonomy-gap-analyst", False),
    ],
)
def test_scan_routes_supported_proposals_and_retains_issue(
    tmp_path, monkeypatch, capsys, source, name, allowed
):
    proposal = _proposal(source, name)
    signals = {source: {"signal_score": 1, "report": {"package_id": name}}, "signals_to_propose": 1}
    monkeypatch.setattr(evolution_signal_collector, "aggregate_signals", lambda: signals)
    monkeypatch.setattr(employee_pack_proposal, "_call_llm", lambda _prompt: proposal)
    output = tmp_path / "outputs"
    proposal_file = tmp_path / "proposal.json"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_REPO", "42433422/XCMAX")
    monkeypatch.setenv("EVOLUTION_PROPOSAL_PATH", str(proposal_file))
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    issue_url = "https://github.com/42433422/XCMAX/issues/3312"
    calls = []

    def open_issue(command, **_kwargs):
        assert command[:3] == ["gh", "issue", "create"]
        assert "--label" not in command
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=issue_url, stderr="")

    script = tmp_path / "scan.py"
    command = shlex.split(_steps()["scan"]["run"])
    assert command[:2] == ["python", "-c"]
    script.write_text(command[2], encoding="utf-8")
    with monkeypatch.context() as isolated:
        isolated.setattr(subprocess, "run", open_issue)
        runpy.run_path(str(script))

    assert proposal["employee_pack"]["prompt_template"] not in capsys.readouterr().out
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert outputs == {"issue_url": issue_url, "scaffold_allowed": str(allowed).lower()}
    assert len(calls) == 1
    assert json.loads(proposal_file.read_text()) == proposal
    events = list_events()
    assert [event["issue_url"] for event in events if event["event_type"] == "issue_opened"] == [
        issue_url
    ]
    deferred = [event for event in events if event.get("final_status") == "needs_human"]
    assert len(deferred) == (0 if allowed else 1)
    if not allowed:
        assert deferred[0]["issue_url"] == issue_url
        assert deferred[0]["proposal_id"] == proposal["proposal_id"]
        assert deferred[0]["triggered_by"] == source
        assert deferred[0]["reason"]
    assert not any(event.get("final_status") in {"completed", "pack_listed"} for event in events)
    generate = _steps()["Generate bounded employee-pack source and open PR"]
    assert generate["if"] == (
        "steps.scan.outputs.issue_url != '' && steps.scan.outputs.scaffold_allowed == 'true'"
    )


def _run_scaffold_handoff(tmp_path, proposal):
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps(proposal), encoding="utf-8")
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    generate = _steps()["Generate bounded employee-pack source and open PR"]
    assert not generate.get("continue-on-error")
    handoff, separator, _publishing = generate["run"].partition("\nbranch=")
    assert separator and "set -euo pipefail" in handoff
    result = subprocess.run(
        ["bash", "-c", handoff + '\nprintf "HANDOFF:%s@%s\\n" "$package_id" "$version"'],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
            "PYTHONPATH": str(MOD_ROOT),
            "GITHUB_WORKSPACE": str(tmp_path),
            "RUNNER_TEMP": str(runner_temp),
            "EVOLUTION_PROPOSAL_PATH": str(proposal_file),
        },
        text=True,
        capture_output=True,
        timeout=15,
    )
    return result, runner_temp / "evolution-scaffold.json"


def test_allowed_scaffold_uses_private_receipt_for_real_workflow_handoff(tmp_path):
    proposal = _proposal()
    result, receipt = _run_scaffold_handoff(tmp_path, proposal)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        '{"file_count": 5, "ok": true}',
        "HANDOFF:autonomy-gap-analyst@1.0.0",
    ]
    payload = json.loads(receipt.read_text())
    assert set(payload) == {"source_dir", "package_id", "version", "file_count"}
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert payload["package_id"] == "autonomy-gap-analyst"
    assert payload["version"] == "1.0.0"
    source_dir = tmp_path / payload["source_dir"]
    files = [path for path in source_dir.rglob("*") if path.is_file()]
    assert len(files) == payload["file_count"] == 5
    private_text = proposal["employee_pack"]["prompt_template"]
    assert all(private_text not in path.read_text() for path in [receipt, *files])
    assert private_text not in result.stdout


@pytest.mark.parametrize(
    "failure", ["unsafe-version", "existing-source", "stale-receipt", "symlink"]
)
def test_scaffold_handoff_blocks_real_errors_and_never_reuses_receipt(tmp_path, failure):
    proposal = _proposal()
    if failure == "unsafe-version":
        proposal["target_version"] = "../../escape"
    elif failure == "existing-source":
        from modstore_server.employee_pack_proposal_scaffold import materialize_proposal

        materialize_proposal(proposal, repo_root=tmp_path)
    else:
        receipt = tmp_path / "runner-temp" / "evolution-scaffold.json"
        receipt.parent.mkdir()
        stale = '{"source_dir":"untrusted","package_id":"untrusted","version":"9.9.9"}'
        if failure == "symlink":
            victim = tmp_path / "must-not-overwrite.json"
            victim.write_text(stale)
            receipt.symlink_to(victim)
        else:
            receipt.write_text(stale)
    result, receipt = _run_scaffold_handoff(tmp_path, proposal)
    assert result.returncode != 0
    assert "HANDOFF:" not in result.stdout
    if failure in {"stale-receipt", "symlink"}:
        assert receipt.read_text() == stale


def test_orchestrator_uses_lightweight_bounded_source_path():
    text = SOURCE.read_text(encoding="utf-8")
    assert "from modstore_server.employee_pack_proposal import propose_employee_pack" in text
    assert "employee_pack_proposal_scaffold" in text
    assert "MODSTORE_ENABLE_CATALOG_GAP_SCAN: 'true'" in text
    assert "automation/evolution-source-${GITHUB_RUN_ID}" in text
    assert 'test "$(find "$source_dir"' in text
    assert "employee_autonomy_service" not in text
    assert "pip install -r requirements.txt 2>/dev/null || true" not in text
    assert "EVOLUTION_IMPLEMENT_WORKFLOW" not in text


def test_orchestrator_recovers_actions_bot_suppressed_push_bootstrap():
    text = SOURCE.read_text(encoding="utf-8")
    assert "workflow_run:" in text
    assert "workflows: ['CI/CD Pipeline']" in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "github.event.workflow_run.head_branch == 'main'" in text
    assert "Decide whether workflow-run bootstrap should scan" in text
    assert "git diff-tree --no-commit-id --name-only" in text
    assert "should_scan=false" in text
    assert "if: steps.scan_scope.outputs.should_scan == 'true'" in text


def test_orchestrator_only_uses_job_level_expression_contexts_available_to_github():
    text = SOURCE.read_text(encoding="utf-8")
    assert "EVOLUTION_PROPOSAL_PATH: ${{ github.workspace }}/.evolution-proposal.json" in text
    assert "EVOLUTION_PROPOSAL_PATH: ${{ runner.temp }}" not in text


def test_exact_cvm_receipt_dispatches_evolution_with_pat():
    text = CI_SOURCE.read_text(encoding="utf-8")
    assert "dispatch-evolution-after-cvm:" in text
    assert "needs: [cvm-push-release]" in text
    assert "inputs.push_to_cvm == true" in text
    assert "needs.cvm-push-release.result == 'success'" in text
    assert "GH_TOKEN: ${{ secrets.CI_COMMIT_TOKEN }}" in text
    assert "gh workflow run fhd-evolution-orchestrator.yml" in text
    assert "-f force_run=false" in text


def test_orchestrator_source_and_published_copy_are_exact():
    source = SOURCE.read_text(encoding="utf-8")
    published = PUBLISHED.read_text(encoding="utf-8")
    assert "\n".join(published.splitlines()[2:]) + "\n" == source
