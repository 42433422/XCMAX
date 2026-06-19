"""Tests for ops_staged_auto_approve."""

from __future__ import annotations

import pytest

from modstore_server.ops_staged_auto_approve import (
    blocked_pattern_hit,
    diff_summary_path_evidence_incomplete,
    should_auto_approve_staged,
)

pytestmark = pytest.mark.release_gate


def test_should_auto_approve_small_diff(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_OPS_STAGED_AUTO_APPROVE", "1")
    monkeypatch.setenv("MODSTORE_OPS_STAGED_AUTO_MAX_FILES", "24")
    assert (
        should_auto_approve_staged(files_changed_count=3, diff_summary="FHD/app/foo.py | 2 +-")
        is True
    )


def test_should_reject_migrations(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_OPS_STAGED_AUTO_APPROVE", "1")
    assert (
        should_auto_approve_staged(files_changed_count=2, diff_summary="migrations/001.py") is False
    )


def test_too_many_files_rejected(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_OPS_STAGED_AUTO_APPROVE", "1")
    monkeypatch.setenv("MODSTORE_OPS_STAGED_AUTO_MAX_FILES", "5")
    assert should_auto_approve_staged(files_changed_count=99, diff_summary="app/a.py") is False


@pytest.mark.parametrize(
    "diff",
    [
        "app/services/payment_gateway.py | 3 +-",
        ".github/workflows/deploy.yml | 2 +-",
        "charts/xcagi/values-production.yaml | 1 +",
        "app/infrastructure/auth/dependencies.py | 4 +-",
        "config/.env.example | 1 +",
        "Dockerfile | 2 +-",
        "pyproject.toml | 1 +",
    ],
)
def test_high_risk_paths_rejected(monkeypatch, diff) -> None:
    monkeypatch.setenv("MODSTORE_OPS_STAGED_AUTO_APPROVE", "1")
    assert should_auto_approve_staged(files_changed_count=1, diff_summary=diff) is False
    assert blocked_pattern_hit(diff) != ""


def test_low_risk_app_change_allowed(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_OPS_STAGED_AUTO_APPROVE", "1")
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_LOOP_MEMORY_JSON", raising=False)
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_MEMORY_JSON", raising=False)
    assert blocked_pattern_hit("app/services/report_text.py | 5 +-") == ""
    assert (
        should_auto_approve_staged(
            files_changed_count=2, diff_summary="app/services/report_text.py | 5 +-"
        )
        is True
    )


def test_compressed_diff_stat_path_rejected_without_changed_files(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_OPS_STAGED_AUTO_APPROVE", "1")
    diff = ".../modstore_server/ops_staged_auto_approve.py | 2 +-"

    assert diff_summary_path_evidence_incomplete(diff) is True
    assert should_auto_approve_staged(files_changed_count=1, diff_summary=diff) is False


def test_explicit_changed_files_drive_high_risk_detection(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_OPS_STAGED_AUTO_APPROVE", "1")

    assert (
        should_auto_approve_staged(
            files_changed_count=1,
            diff_summary=".../app_factory.py | 2 +-",
            changed_files=[
                "成都修茈科技有限公司/MODstore_deploy/modstore_server/api/app_factory.py",
            ],
        )
        is False
    )


def test_slo_halt_blocks_auto_approve(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_OPS_STAGED_AUTO_APPROVE", "1")
    monkeypatch.setenv("MODSTORE_RELEASE_SLO_HALT", "1")
    monkeypatch.setattr(
        "modstore_server.post_deploy_smoke.run_post_deploy_smoke",
        lambda **_: {"ok": False, "skipped": False, "probes": []},
    )
    assert should_auto_approve_staged(files_changed_count=3, diff_summary="FHD/foo.py") is False


def test_marker_only_self_maintenance_status_rejected_after_review_risk(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_OPS_STAGED_AUTO_APPROVE", "1")
    monkeypatch.setenv(
        "MODSTORE_SELF_MAINTENANCE_LOOP_MEMORY_JSON",
        '{"last_policy_decision":{"action":"await_human_strategy_approval","reason":"review_or_qa_reported_risk"},"open_items":[]}',
    )

    assert (
        should_auto_approve_staged(
            files_changed_count=1,
            diff_summary=(
                "成都修茈科技有限公司/MODstore_deploy/modstore_server/"
                "self_maintenance_loop_status.py | 1 +"
            ),
        )
        is False
    )
