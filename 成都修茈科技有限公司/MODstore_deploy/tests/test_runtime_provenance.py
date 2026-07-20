from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from modstore_server import self_maintenance_loop_runner as loop_runner
from modstore_server.runtime_provenance import collect_runtime_provenance


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _clean_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "autonomy@example.invalid")
    _git(repo, "config", "user.name", "Autonomy Test")
    (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_clean_exact_sha_checkout_is_trusted(tmp_path: Path) -> None:
    repo, sha = _clean_repo(tmp_path)

    snapshot = collect_runtime_provenance(
        repo_root=repo,
        target_branch="main",
        expected_sha=sha,
    )

    assert snapshot["ok"] is True
    assert snapshot["clean"] is True
    assert snapshot["head_sha"] == sha
    assert snapshot["target_sha"] == sha
    assert snapshot["reasons"] == []


def test_dirty_checkout_is_blocked(tmp_path: Path) -> None:
    repo, sha = _clean_repo(tmp_path)
    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")

    snapshot = collect_runtime_provenance(
        repo_root=repo,
        target_branch="main",
        expected_sha=sha,
    )

    assert snapshot["ok"] is False
    assert "dirty_worktree" in snapshot["reasons"]
    assert snapshot["dirty_paths"] == ["tracked.txt"]


def test_wrong_branch_is_blocked(tmp_path: Path) -> None:
    repo, sha = _clean_repo(tmp_path)
    _git(repo, "switch", "-c", "feature/not-runtime")

    snapshot = collect_runtime_provenance(
        repo_root=repo,
        target_branch="main",
        expected_sha=sha,
    )

    assert snapshot["ok"] is False
    assert "branch_mismatch" in snapshot["reasons"]


def test_immutable_runtime_requires_matching_build_and_expected_sha(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MODSTORE_GIT_SHA", "abc123")
    monkeypatch.setenv("MODSTORE_EXPECTED_GIT_SHA", "abc123")
    monkeypatch.delenv("MODSTORE_REPO_ROOT", raising=False)
    monkeypatch.delenv("XCMAX_MONOREPO_ROOT", raising=False)
    monkeypatch.setattr(
        "modstore_server.runtime_provenance.resolve_runtime_repo_root",
        lambda explicit=None: None,
    )

    snapshot = collect_runtime_provenance(repo_root=tmp_path / "not-a-repo")

    assert snapshot["ok"] is True
    assert snapshot["source"] == "immutable_environment"


def test_cleanroom_runtime_verifies_manifest_file_hashes(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    critical = runtime / "runner.py"
    critical.write_text("trusted = True\n", encoding="utf-8")
    digest = hashlib.sha256(critical.read_bytes()).hexdigest()
    manifest = runtime / ".xcmax-runtime-provenance.json"
    manifest.write_text(
        json.dumps(
            {
                "files": {"runner.py": digest},
                "git_sha": "a" * 40,
                "runtime_root": str(runtime),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_GIT_SHA", "a" * 40)
    monkeypatch.setenv("MODSTORE_EXPECTED_GIT_SHA", "a" * 40)
    monkeypatch.setenv("MODSTORE_DAILY_ENV_CLEANROOM", "1")
    monkeypatch.setenv("MODSTORE_RELEASE_MANIFEST", str(manifest))
    monkeypatch.setattr(
        "modstore_server.runtime_provenance.resolve_runtime_repo_root",
        lambda explicit=None: None,
    )

    trusted = collect_runtime_provenance(repo_root=tmp_path / "not-a-repo")
    critical.write_text("trusted = False\n", encoding="utf-8")
    tampered = collect_runtime_provenance(repo_root=tmp_path / "not-a-repo")

    assert trusted["ok"] is True
    assert trusted["source"] == "immutable_manifest"
    assert trusted["verified_files"] == ["runner.py"]
    assert tampered["ok"] is False
    assert "runtime_file_hash_mismatch:runner.py" in tampered["reasons"]


def test_ledger_adds_correlation_id_and_schema(monkeypatch, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_LEDGER", str(ledger))

    loop_runner._append_ledger({"phase": "start", "run_id": "run-123"})

    record = json.loads(ledger.read_text(encoding="utf-8"))
    assert record["correlation_id"] == "run-123"
    assert record["ledger_schema_version"] == 2


def test_force_cannot_bypass_untrusted_runtime_provenance(monkeypatch) -> None:
    monkeypatch.setattr(
        loop_runner,
        "evaluate_self_maintenance_need",
        lambda: {
            "runtime_provenance": {
                "ok": False,
                "reasons": ["dirty_worktree"],
            },
            "signal_count": 99,
        },
    )

    result = loop_runner.should_run_self_maintenance_loop(force=True)

    assert result["should_run"] is False
    assert result["reason"] == "runtime_provenance_blocked"
    assert result["force_requested"] is True


def test_loop_lease_is_exclusive(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "MODSTORE_SELF_MAINTENANCE_LEASE_FILE",
        str(tmp_path / "loop.lock"),
    )

    with loop_runner._exclusive_loop_lease() as first:
        with loop_runner._exclusive_loop_lease() as second:
            assert first is True
            assert second is False
