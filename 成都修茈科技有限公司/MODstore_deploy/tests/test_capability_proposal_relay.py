"""本地能力提案中继：发现、互斥、收据与后置条件。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import modstore_server.capability_proposal_relay as relay
from modstore_server.evolution_ledger import list_events


@pytest.fixture
def relay_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / "XCMAX"
    report_dir = root / "FHD" / "test_reports"
    script = root / "FHD" / "scripts" / "dev" / "capability_proposal_to_issue.py"
    report_dir.mkdir(parents=True)
    script.parent.mkdir(parents=True)
    script.write_text("# test relay\n", encoding="utf-8")
    monkeypatch.setenv("MODSTORE_GIT_REPO_ROOT", str(root))
    monkeypatch.setenv("MODSTORE_CAPABILITY_PROPOSAL_REPO", "acme/repo")
    monkeypatch.setattr(relay.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.delenv("XCAGI_FHD_ROOT", raising=False)
    monkeypatch.delenv("MODSTORE_CAPABILITY_PROPOSAL_DIRS", raising=False)
    return root, report_dir


def _write_proposal(report_dir: Path, key: str = "proposal-key") -> None:
    (report_dir / "capability_proposal.jsonl").write_text(
        json.dumps({"dedup_key": key, "reason": "skill_proposal"}) + "\n",
        encoding="utf-8",
    )


def test_parse_repo_slug_supports_https_and_ssh() -> None:
    assert relay._parse_repo_slug("https://github.com/acme/repo.git") == "acme/repo"
    assert relay._parse_repo_slug("git@github.com:acme/repo.git") == "acme/repo"
    assert relay._parse_repo_slug("https://example.com/acme/repo") == ""


def test_no_proposal_file_is_no_action(relay_root: tuple[Path, Path]) -> None:
    result = relay.run_capability_proposal_relay()
    assert result == {"ok": True, "status": "no_candidates", "scanned_dirs": 0}


def test_deployed_runtime_script_precedes_dirty_source_checkout(
    relay_root: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _root, _report_dir = relay_root
    runtime = tmp_path / "runtime-fhd"
    script = runtime / "scripts" / "dev" / "capability_proposal_to_issue.py"
    script.parent.mkdir(parents=True)
    script.write_text("# deployed\n", encoding="utf-8")
    monkeypatch.setenv("XCAGI_FHD_ROOT", str(runtime))
    assert relay._script_path() == script.resolve()


def test_success_requires_new_processed_receipt(
    relay_root: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, report_dir = relay_root
    _write_proposal(report_dir)
    events: list[dict] = []
    monkeypatch.setattr(relay, "_append_evolution_event", events.append)

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        assert "--gh-cli" in command
        assert "--apply" in command
        target = Path(kwargs["env"]["CAPABILITY_PROPOSAL_DIR"])
        (target / "capability_proposal_processed.jsonl").write_text(
            json.dumps(
                {
                    "dedup_key": "proposal-key",
                    "disposition": "issue_created",
                    "issue_url": "https://github.com/acme/repo/issues/9",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(relay.subprocess, "run", fake_run)
    result = relay.run_capability_proposal_relay()

    assert result["ok"] is True
    assert result["created_count"] == 1
    assert result["pending_after"] == 0
    assert result["postcondition"]["processed_receipts_written"] == 1
    assert result["issue_urls"] == ["https://github.com/acme/repo/issues/9"]
    assert len(events) == 1
    assert not (report_dir / "capability_proposal_relay.lock").exists()


def test_failed_child_is_reported_and_lease_is_cleaned(
    relay_root: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, report_dir = relay_root
    _write_proposal(report_dir)
    events: list[dict] = []
    monkeypatch.setattr(relay, "_append_evolution_event", events.append)
    monkeypatch.setattr(
        relay.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 1, stdout="", stderr="auth failed"
        ),
    )

    result = relay.run_capability_proposal_relay()

    assert result["ok"] is False
    assert result["status"] == "relay_failed"
    assert result["pending_after"] == 1
    assert len(events) == 1
    assert not (report_dir / "capability_proposal_relay.lock").exists()


def test_token_transport_stays_out_of_child_command(
    relay_root: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, report_dir = relay_root
    _write_proposal(report_dir)
    monkeypatch.setenv("MODSTORE_GITHUB_TOKEN", "test-token")
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed["environment"] = kwargs["env"]
        target = Path(kwargs["env"]["CAPABILITY_PROPOSAL_DIR"])
        (target / "capability_proposal_processed.jsonl").write_text(
            json.dumps({"dedup_key": "proposal-key", "disposition": "issue_created"}) + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(relay.subprocess, "run", fake_run)
    result = relay.run_capability_proposal_relay()

    assert result["ok"] is True
    assert "--gh-cli" not in observed["command"]
    assert "test-token" not in observed["command"]
    assert observed["environment"]["GITHUB_TOKEN"] == "test-token"


def test_candidate_without_github_transport_is_configuration_blocked(
    relay_root: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, report_dir = relay_root
    _write_proposal(report_dir)
    monkeypatch.delenv("MODSTORE_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(relay.shutil, "which", lambda _name: None)
    events: list[dict] = []
    monkeypatch.setattr(relay, "_configuration_block_has_recent_audit", lambda _errors: False)
    monkeypatch.setattr(relay, "_append_evolution_event", lambda event: events.append(dict(event)))

    result = relay.run_capability_proposal_relay()

    assert result["ok"] is False
    assert result["status"] == "configuration_blocked"
    assert result["configuration_errors"] == ["github_credentials_unavailable"]
    assert result["audit_event_written"] is True
    assert result["remediation"].startswith("provision MODSTORE_GITHUB_TOKEN")
    assert events == [
        {
            "ok": False,
            "status": "configuration_blocked",
            "scanned_dirs": 1,
            "created_count": 0,
            "ignored_count": 0,
            "pending_after": 0,
            "issue_urls": [],
            "results": [],
            "configuration_errors": ["github_credentials_unavailable"],
            "remediation": (
                "provision MODSTORE_GITHUB_TOKEN or an authenticated gh client "
                "through protected runtime configuration"
            ),
        }
    ]
    assert "proposal-key" not in str(events)


def test_configuration_block_audit_is_deduplicated(
    relay_root: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _root, report_dir = relay_root
    _write_proposal(report_dir)
    monkeypatch.delenv("MODSTORE_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(relay.shutil, "which", lambda _name: None)
    monkeypatch.setenv("MODSTORE_EVOLUTION_LEDGER_PATH", str(tmp_path / "evolution.jsonl"))

    first = relay.run_capability_proposal_relay()
    result = relay.run_capability_proposal_relay()

    assert first["audit_event_written"] is True
    assert result["status"] == "configuration_blocked"
    assert result["audit_event_written"] is False
    assert result["audit_event_reason"] == "duplicate_within_24h"
    events = list_events(
        event_type="capability_proposal_relay_completed",
        final_status="configuration_blocked",
    )
    assert len(events) == 1
    assert events[0]["configuration_errors"] == ["github_credentials_unavailable"]
    assert events[0]["remediation"].startswith("provision MODSTORE_GITHUB_TOKEN")
    assert "proposal-key" not in str(events[0])


def test_scheduler_registration_tracks_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs: list[tuple[object, dict]] = []

    class FakeScheduler:
        def add_job(self, fn, _trigger, **kwargs) -> None:
            jobs.append((fn, kwargs))

    tracked: list[str] = []

    def track_job(job_id: str, fn):
        tracked.append(job_id)
        return fn()

    monkeypatch.setattr(
        relay,
        "run_capability_proposal_relay",
        lambda: {"ok": True, "status": "no_candidates"},
    )
    relay.register_capability_proposal_relay_job(FakeScheduler(), track_job=track_job)

    assert jobs[0][1]["id"] == "capability_proposal_relay"
    jobs[0][0]()
    assert tracked == ["capability_proposal_relay"]


def test_disabled_relay_stays_registered_for_scheduler_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs: list[tuple[object, dict]] = []

    class FakeScheduler:
        def add_job(self, fn, _trigger, **kwargs) -> None:
            jobs.append((fn, kwargs))

    monkeypatch.setenv("MODSTORE_CAPABILITY_PROPOSAL_RELAY_ENABLED", "0")
    tracked: list[str] = []

    def track_job(job_id: str, fn):
        tracked.append(job_id)
        return fn()

    relay.register_capability_proposal_relay_job(
        FakeScheduler(),
        track_job=track_job,
    )
    jobs[0][0]()
    assert tracked == ["capability_proposal_relay"]
