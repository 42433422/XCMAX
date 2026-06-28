from __future__ import annotations

from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.service import RetortService
from retort_engine.upstream_pr_ci_probe import build_upstream_pr_ci_probe


def test_upstream_pr_ci_probe_accepts_merged_pr_with_successful_checks(tmp_path: Path) -> None:
    result = build_upstream_pr_ci_probe(tmp_path, fetcher=_fetcher)

    assert result["status"] == "ready"
    assert result["summary"]["merged"] is True
    assert result["summary"]["all_check_runs_successful"] is True
    assert result["summary"]["check_run_count"] == 2
    assert validate_contract("upstream_pr_ci_probe_result", result)["valid"] is True


def test_upstream_pr_ci_probe_blocks_failed_checks(tmp_path: Path) -> None:
    def fetcher(path: str) -> dict:
        payload = _fetcher(path)
        if "check-runs" in path:
            payload["check_runs"][1]["conclusion"] = "failure"
        return payload

    result = build_upstream_pr_ci_probe(tmp_path, fetcher=fetcher)

    assert result["status"] == "needs_upstream_pr_ci_evidence"
    assert result["summary"]["failed_check_run_count"] == 1


def test_service_exposes_upstream_pr_ci_probe_with_real_defaults_shape(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("retort_engine.upstream_pr_ci_probe._gh_api", _fetcher)

    result = RetortService().upstream_pr_ci_probe({"project": str(tmp_path)})

    assert result["status"] == "ready"
    assert result["summary"]["merge_commit_sha"] == "abc123"


def _fetcher(path: str) -> dict:
    if path.endswith("/pulls/7539"):
        return {
            "html_url": "https://github.com/psf/requests/pull/7539",
            "merged": True,
            "merged_at": "2026-06-24T22:40:13Z",
            "merge_commit_sha": "abc123",
        }
    if "check-runs" in path:
        return {
            "total_count": 2,
            "check_runs": [
                {"name": "lint", "status": "completed", "conclusion": "success", "html_url": "https://example.test/1"},
                {"name": "test", "status": "completed", "conclusion": "success", "html_url": "https://example.test/2"},
            ],
        }
    raise AssertionError(path)
