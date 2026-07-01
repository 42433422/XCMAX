"""Cov90b: behavior tests for SixLineEventAppService uncovered branches.

Targets uncovered lines in app/application/six_line_event_app_service.py:
  - match_route early/no-match returns (42, 52)
  - dispatch unrouted path (72-75)
  - _post_incident_remote base-set success / secret header / recoverable error
    (133-149)
  - status_snapshot graph_nodes loop (157-159)
  - list_backlog_for_digest file read + JSON decode handling (174-189)
  - get_six_line_event_app_service factory (193)

All external dependencies (loader IO, httpx, env, filesystem) are mocked or
redirected to tmp_path; deterministic and offline.
"""

from __future__ import annotations

import json

import pytest

from app.application.six_line_event_app_service import (
    SixLineEventAppService,
    get_six_line_event_app_service,
)
from app.infrastructure.six_line import event_route_loader as loader

# Minimal, self-contained routes config so tests do not depend on the shipped
# config file contents.
_ROUTES_CONFIG = {
    "version": "test-1",
    "operations_line": [
        {
            "id": "op-backlog",
            "action": "digest_backlog",
            "step_id": "O7",
            "line_step": "O7",
            "status_in": ["progress", "completed"],
            "event_type": "ops.demo.backlog",
            "dispatch_line": "P-S",
            "list_kind": "patches",
            "priority": "P2",
        },
    ],
    "cross_line": [
        {
            "id": "xl-incident",
            "action": "incident",
            "line_step": "P2",
            "event_type": "ops.intake.task.queued",
            "dispatch_line": "P-S",
            "priority": "P1",
        },
    ],
    "incident_defaults": [
        {
            # Step-scoped incident so an unknown step_id will NOT match it; this
            # keeps line-52 (no-match) reachable for step lookups.
            "id": "inc-payment-anomaly",
            "action": "incident",
            "step_id": "O4",
            "line_step": "O4",
            "event_type": "payment.anomaly",
            "priority": "P0",
        },
    ],
}


@pytest.fixture()
def cs_dir(tmp_path, monkeypatch):
    """Redirect all loader IO into tmp_path/customer_service and stub config."""
    cs = tmp_path / "customer_service"
    cs.mkdir()
    monkeypatch.setattr(loader, "_customer_service_dir", lambda: cs)
    monkeypatch.setattr(loader, "load_routes_config", lambda: dict(_ROUTES_CONFIG))
    # Deterministic timestamp.
    monkeypatch.setattr(loader, "utc_now_iso", lambda: "2026-06-24T00:00:00+00:00")
    return cs


@pytest.fixture()
def svc(cs_dir):
    return SixLineEventAppService()


# --------------------------------------------------------------------------
# match_route: line 42 (no sid and no event_type) and line 52 (no match)
# --------------------------------------------------------------------------


def test_match_route_no_step_no_event_returns_none(svc: SixLineEventAppService):
    assert svc.match_route(step_id=None, status="progress", event_type=None) is None
    # Whitespace-only step_id strips to empty and counts as missing.
    assert svc.match_route(step_id="   ", status="progress", event_type=None) is None


def test_match_route_event_type_no_match_returns_none(svc: SixLineEventAppService):
    # event_type present but matches no route, no sid -> falls through to line 52.
    assert svc.match_route(event_type="totally.unknown.event") is None


def test_match_route_step_no_match_returns_none(svc: SixLineEventAppService):
    # sid present but no route's step matches -> falls through to line 52.
    assert svc.match_route(step_id="ZZZ", status="progress") is None


def test_match_route_event_type_with_unmatched_step(svc: SixLineEventAppService):
    # event_type matches a route, but the provided sid does not satisfy
    # matches_step_status for that route -> no return inside the event branch;
    # sid branch then finds no step match -> line 52 returns None.
    assert svc.match_route(step_id="ZZZ", status="progress", event_type="payment.anomaly") is None


def test_match_route_event_type_match_no_step(svc: SixLineEventAppService):
    route = svc.match_route(event_type="payment.anomaly")
    assert route is not None
    assert route.id == "inc-payment-anomaly"


def test_match_route_step_match(svc: SixLineEventAppService):
    route = svc.match_route(step_id="O7", status="progress")
    assert route is not None
    assert route.id == "op-backlog"


# --------------------------------------------------------------------------
# dispatch: lines 72-75 (unrouted)
# --------------------------------------------------------------------------


def test_dispatch_unrouted_writes_audit(svc: SixLineEventAppService, cs_dir):
    out = svc.dispatch({"step_id": "NOPE", "status": "progress"})
    assert out == {"success": True, "matched": False, "action": "unrouted"}

    audit_path = cs_dir / "six_line_event_audit.jsonl"
    assert audit_path.is_file()
    row = json.loads(audit_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["matched"] is False
    assert row["action"] == "unrouted"
    assert row["step_id"] == "NOPE"
    assert row["at"] == "2026-06-24T00:00:00+00:00"


def test_dispatch_empty_event_type_normalized_to_none(svc: SixLineEventAppService, cs_dir):
    # event_type is a blank string -> normalized to None (line 59) and unrouted.
    out = svc.dispatch({"step_id": "", "status": "progress", "event_type": "   "})
    assert out["matched"] is False
    row = json.loads(
        (cs_dir / "six_line_event_audit.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
    )
    assert row["event_type"] is None


# --------------------------------------------------------------------------
# _post_incident_remote: 132-149
# --------------------------------------------------------------------------


def test_post_incident_remote_no_base_returns_false(svc: SixLineEventAppService, monkeypatch):
    monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
    assert svc._post_incident_remote({"route_id": "x"}) is False


def test_post_incident_remote_success_with_secret(svc: SixLineEventAppService, monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com/")
    monkeypatch.setenv("XCAGI_OPS_LINE_HOOK_SECRET", "s3cr3t")

    captured: dict = {}

    class _Resp:
        is_success = True

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)

    entry = {"route_id": "inc-payment-anomaly", "priority": "P0"}
    assert svc._post_incident_remote(entry) is True
    # base trailing slash stripped, path appended.
    assert captured["url"] == "https://market.example.com/api/admin/production-line/incident"
    assert captured["json"] == entry
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["headers"]["X-Ops-Line-Secret"] == "s3cr3t"
    assert captured["timeout"] == 5.0


def test_post_incident_remote_no_secret_omits_header(svc: SixLineEventAppService, monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")
    monkeypatch.delenv("XCAGI_OPS_LINE_HOOK_SECRET", raising=False)

    captured: dict = {}

    class _Resp:
        is_success = False

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured["headers"] = headers
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)

    # is_success False -> returns False, header absent.
    assert svc._post_incident_remote({"route_id": "x"}) is False
    assert "X-Ops-Line-Secret" not in captured["headers"]


def test_post_incident_remote_recoverable_error_returns_false(
    svc: SixLineEventAppService, monkeypatch
):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")

    import httpx

    def boom(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", boom)
    assert svc._post_incident_remote({"route_id": "x"}) is False


def test_dispatch_incident_remote_success_skips_outbox(
    svc: SixLineEventAppService, cs_dir, monkeypatch
):
    # When remote post succeeds, the incident outbox should NOT be written.
    monkeypatch.setattr(SixLineEventAppService, "_post_incident_remote", lambda self, entry: True)
    out = svc.dispatch({"event_type": "payment.anomaly", "status": "anomaly"})
    assert out["matched"] is True
    assert out["action"] == "incident"
    result = out["results"][0]
    assert result["sink"] == "incident_bus"
    assert result["remote"] is True
    assert not (cs_dir / "incident_outbox.jsonl").is_file()


def test_dispatch_incident_remote_failure_writes_outbox(
    svc: SixLineEventAppService, cs_dir, monkeypatch
):
    monkeypatch.setattr(SixLineEventAppService, "_post_incident_remote", lambda self, entry: False)
    out = svc.dispatch({"event_type": "payment.anomaly", "status": "anomaly"})
    assert out["matched"] is True
    outbox = cs_dir / "incident_outbox.jsonl"
    assert outbox.is_file()
    row = json.loads(outbox.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["event_type"] == "payment.anomaly"
    assert row["priority"] == "P0"


# --------------------------------------------------------------------------
# status_snapshot: lines 157-159 graph_nodes accumulation
# --------------------------------------------------------------------------


def test_status_snapshot_graph_nodes_from_recent(svc: SixLineEventAppService, cs_dir, monkeypatch):
    recent = [
        {"route_id": "r1", "at": "t1"},
        {"at": "t2"},  # no route_id -> skipped in route_ids and graph_nodes
        {"route_id": "r2", "at": "t3"},
        {"route_id": "r1", "at": "t4"},  # duplicate id de-duped in recent_route_ids
    ]
    monkeypatch.setattr(loader, "read_recent_audit", lambda limit=30: recent)
    monkeypatch.setattr(loader, "count_jsonl_pending", lambda name: 0)

    snap = svc.status_snapshot()
    assert snap["operations_routes"] == 1
    assert snap["cross_line_routes"] == 1
    assert snap["incident_defaults"] == 1
    assert snap["last_event_at"] == "t4"
    assert snap["recent_route_ids"] == ["r1", "r2"]
    assert snap["version"] == "test-1"


def test_status_snapshot_empty_audit(svc: SixLineEventAppService, monkeypatch):
    monkeypatch.setattr(loader, "read_recent_audit", lambda limit=30: [])
    monkeypatch.setattr(loader, "count_jsonl_pending", lambda name: 0)
    snap = svc.status_snapshot()
    assert snap["last_event_at"] is None
    assert snap["recent_route_ids"] == []


# --------------------------------------------------------------------------
# list_backlog_for_digest: lines 174-189
# --------------------------------------------------------------------------


def test_list_backlog_for_digest_missing_file(svc: SixLineEventAppService, cs_dir):
    # No backlog file present -> empty list (line 175-176).
    assert svc.list_backlog_for_digest() == []


def test_list_backlog_for_digest_reads_and_skips_bad_lines(svc: SixLineEventAppService, cs_dir):
    path = cs_dir / "six_line_digest_backlog.jsonl"
    path.write_text(
        '{"id": 1}\n'
        "\n"  # blank line -> skipped (line 183-184)
        "not-json\n"  # JSONDecodeError -> skipped (line 187-188)
        '   {"id": 2}   \n',  # surrounding whitespace stripped, still parsed
        encoding="utf-8",
    )
    out = svc.list_backlog_for_digest()
    assert out == [{"id": 1}, {"id": 2}]


def test_list_backlog_for_digest_respects_limit(svc: SixLineEventAppService, cs_dir):
    path = cs_dir / "six_line_digest_backlog.jsonl"
    path.write_text(
        "".join(f'{{"n": {i}}}\n' for i in range(5)),
        encoding="utf-8",
    )
    out = svc.list_backlog_for_digest(limit=2)
    # Only the last 2 lines are kept.
    assert out == [{"n": 3}, {"n": 4}]


# --------------------------------------------------------------------------
# get_six_line_event_app_service factory: line 193
# --------------------------------------------------------------------------


def test_factory_returns_service_instance():
    svc = get_six_line_event_app_service()
    assert isinstance(svc, SixLineEventAppService)
    # Each call yields a fresh instance.
    assert svc is not get_six_line_event_app_service()
