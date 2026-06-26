"""Extended branch coverage tests for six_line_event_app_service.

Covers missing branches in:
- _config (cache hit/miss)
- _all_routes (missing keys, non-dict items, missing id)
- match_route (no sid/event_type, event_type only, sid only, no match)
- dispatch (unrouted, event_type stripping, payload dict check, incident remote post)
- _post_incident_remote (no base url, with/without secret, httpx error)
- status_snapshot (empty recent, with recent)
- list_backlog_for_digest (file not found, empty lines, invalid json, limit)
- get_six_line_event_app_service
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.application.six_line_event_app_service import (
    SixLineEventAppService,
    get_six_line_event_app_service,
)
from app.infrastructure.six_line import event_route_loader as loader

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg_dir(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    src = Path(__file__).resolve().parents[2] / "config" / "six_line_event_routes.json"
    (cfg_dir / "six_line_event_routes.json").write_text(
        src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return cfg_dir


@pytest.fixture
def cs_dir(tmp_path):
    cs = tmp_path / "customer_service"
    cs.mkdir()
    return cs


@pytest.fixture
def svc(cfg_dir, cs_dir, monkeypatch):
    monkeypatch.setattr(loader, "_config_path", lambda: cfg_dir / "six_line_event_routes.json")
    monkeypatch.setattr(loader, "_customer_service_dir", lambda: cs_dir)
    return SixLineEventAppService()


# ---------------------------------------------------------------------------
# _config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_config_loaded_once(self, svc):
        """Config should be loaded only once and cached."""
        with patch.object(
            loader, "load_routes_config", wraps=loader.load_routes_config
        ) as mock_load:
            cfg1 = svc._config()
            cfg2 = svc._config()
            assert cfg1 is cfg2
            assert mock_load.call_count == 1


# ---------------------------------------------------------------------------
# _all_routes
# ---------------------------------------------------------------------------


class TestAllRoutes:
    def test_routes_loaded_from_config(self, svc):
        routes = svc._all_routes()
        assert len(routes) > 0
        # Each route should have an id
        for route in routes:
            assert route.id

    def test_routes_include_operations_line(self, svc):
        routes = svc._all_routes()
        # The config should have operations_line routes
        assert len(routes) > 0

    def test_missing_keys_return_empty(self, tmp_path, monkeypatch):
        """When config has missing keys, _all_routes handles gracefully."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "six_line_event_routes.json").write_text(
            json.dumps({"version": "1.0"}),  # No operations_line/cross_line/incident_defaults
            encoding="utf-8",
        )
        cs = tmp_path / "customer_service"
        cs.mkdir()

        monkeypatch.setattr(loader, "_config_path", lambda: cfg_dir / "six_line_event_routes.json")
        monkeypatch.setattr(loader, "_customer_service_dir", lambda: cs)

        svc = SixLineEventAppService()
        routes = svc._all_routes()
        assert routes == []

    def test_non_dict_items_skipped(self, tmp_path, monkeypatch):
        """Non-dict items in config lists should be skipped."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "six_line_event_routes.json").write_text(
            json.dumps(
                {
                    "operations_line": [
                        "not a dict",
                        123,
                        None,
                        {"id": "route-1", "step_id": "O1", "action": "digest_backlog"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        cs = tmp_path / "customer_service"
        cs.mkdir()

        monkeypatch.setattr(loader, "_config_path", lambda: cfg_dir / "six_line_event_routes.json")
        monkeypatch.setattr(loader, "_customer_service_dir", lambda: cs)

        svc = SixLineEventAppService()
        routes = svc._all_routes()
        assert len(routes) == 1
        assert routes[0].id == "route-1"

    def test_items_without_id_skipped(self, tmp_path, monkeypatch):
        """Dict items without 'id' should be skipped."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "six_line_event_routes.json").write_text(
            json.dumps(
                {
                    "operations_line": [
                        {"step_id": "O1", "action": "digest_backlog"},  # no id
                        {"id": "", "step_id": "O2"},  # empty id
                        {"id": "route-1", "step_id": "O3", "action": "digest_backlog"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        cs = tmp_path / "customer_service"
        cs.mkdir()

        monkeypatch.setattr(loader, "_config_path", lambda: cfg_dir / "six_line_event_routes.json")
        monkeypatch.setattr(loader, "_customer_service_dir", lambda: cs)

        svc = SixLineEventAppService()
        routes = svc._all_routes()
        assert len(routes) == 1
        assert routes[0].id == "route-1"


# ---------------------------------------------------------------------------
# match_route
# ---------------------------------------------------------------------------


class TestMatchRoute:
    def test_no_step_id_no_event_type_returns_none(self, svc):
        result = svc.match_route(step_id=None, event_type=None)
        assert result is None

    def test_empty_step_id_no_event_type_returns_none(self, svc):
        result = svc.match_route(step_id="", event_type=None)
        assert result is None

    def test_whitespace_step_id_no_event_type_returns_none(self, svc):
        result = svc.match_route(step_id="   ", event_type=None)
        assert result is None

    def test_step_id_only_matches(self, svc):
        result = svc.match_route(step_id="O7", status="progress")
        assert result is not None
        assert result.action == "digest_backlog"

    def test_event_type_only_matches(self, svc):
        result = svc.match_route(event_type="payment.anomaly")
        assert result is not None

    def test_event_type_with_step_id_matches(self, svc):
        result = svc.match_route(step_id="O4", status="anomaly", event_type="payment.anomaly")
        assert result is not None

    def test_no_match_returns_none(self, svc):
        """When no route matches, should return None.

        Note: incident_defaults routes have step_id=None and act as catch-alls,
        so we patch _all_routes to return [] to test the no-match branch.
        """
        with patch.object(svc, "_all_routes", return_value=[]):
            result = svc.match_route(step_id="NONEXISTENT", status="unknown")
        assert result is None

    def test_event_type_no_match_falls_to_step_id(self, svc):
        """When event_type doesn't match, falls through to step_id matching."""
        result = svc.match_route(step_id="O7", status="progress", event_type="nonexistent.type")
        # Should still match via step_id
        assert result is not None

    def test_event_type_matches_but_step_id_doesnt(self, svc):
        """When event_type matches but step_id doesn't match the route,
        should continue looking."""
        # event_type matches but step_id is different
        result = svc.match_route(
            step_id="NONEXISTENT", status="progress", event_type="payment.anomaly"
        )
        # Should match via event_type since step_id doesn't match
        # but the route for payment.anomaly might not match NONEXISTENT step
        # So it falls through to step_id matching which also fails
        # Result depends on whether any route matches event_type without step_id check
        assert result is not None  # event_type match without step_id check


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_unrouted_event(self, svc, cs_dir):
        """When no route matches, dispatch returns unrouted.

        Note: incident_defaults routes act as catch-alls (step_id=None),
        so we patch _all_routes to return [] to test the unrouted branch.
        """
        with patch.object(svc, "_all_routes", return_value=[]):
            result = svc.dispatch({"step_id": "NONEXISTENT", "status": "unknown"})
        assert result["success"] is True
        assert result["matched"] is False
        assert result["action"] == "unrouted"

    def test_event_type_stripped(self, svc, cs_dir):
        """event_type with whitespace should be stripped."""
        result = svc.dispatch(
            {"step_id": "O4", "status": "anomaly", "event_type": "  payment.anomaly  "}
        )
        assert result["matched"] is True

    def test_event_type_empty_after_strip_becomes_none(self, svc, cs_dir):
        """event_type that's only whitespace should become None."""
        result = svc.dispatch({"step_id": "O7", "status": "progress", "event_type": "   "})
        # event_type becomes None, so matching is by step_id only
        assert result["matched"] is True

    def test_payload_not_dict_uses_empty_dict(self, svc, cs_dir):
        """When payload.get('payload') is not a dict, body should be {}."""
        result = svc.dispatch({"step_id": "O7", "status": "completed", "payload": "not a dict"})
        assert result["matched"] is True
        # The dispatch should still work with empty body

    def test_payload_none_uses_empty_dict(self, svc, cs_dir):
        result = svc.dispatch({"step_id": "O7", "status": "completed"})
        assert result["matched"] is True

    def test_status_defaults_to_progress(self, svc, cs_dir):
        """When status is missing, defaults to 'progress'."""
        result = svc.dispatch({"step_id": "O7"})
        assert result["matched"] is True

    def test_status_whitespace_stripped(self, svc, cs_dir):
        result = svc.dispatch({"step_id": "O7", "status": "  progress  "})
        assert result["matched"] is True

    def test_step_id_whitespace_stripped(self, svc, cs_dir):
        result = svc.dispatch({"step_id": "  O7  ", "status": "progress"})
        assert result["matched"] is True

    def test_incident_action_writes_to_outbox(self, svc, cs_dir):
        result = svc.dispatch(
            {"step_id": "O4", "status": "anomaly", "event_type": "payment.anomaly"}
        )
        assert result["matched"] is True
        assert result["action"] == "incident"
        outbox = cs_dir / "incident_outbox.jsonl"
        assert outbox.is_file()

    def test_incident_remote_post_success(self, svc, cs_dir, monkeypatch):
        """When remote post succeeds, should not write to outbox."""
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")

        # Clear the outbox file first
        outbox = cs_dir / "incident_outbox.jsonl"
        if outbox.exists():
            outbox.unlink()

        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_post.return_value = mock_resp
            result = svc.dispatch(
                {"step_id": "O4", "status": "anomaly", "event_type": "payment.anomaly"}
            )

        assert result["matched"] is True
        # Check that results include remote=True
        incident_result = [r for r in result.get("results", []) if r.get("sink") == "incident_bus"]
        assert len(incident_result) == 1
        assert incident_result[0]["remote"] is True
        # Outbox should not have been written to
        assert not outbox.exists()

    def test_incident_remote_post_with_secret(self, svc, cs_dir, monkeypatch):
        """When secret is set, it should be included in headers."""
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")
        monkeypatch.setenv("XCAGI_OPS_LINE_HOOK_SECRET", "secret123")

        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_post.return_value = mock_resp
            svc.dispatch({"step_id": "O4", "status": "anomaly", "event_type": "payment.anomaly"})

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["X-Ops-Line-Secret"] == "secret123"

    def test_incident_remote_post_failure_writes_outbox(self, svc, cs_dir, monkeypatch):
        """When remote post fails, should write to outbox."""
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")

        outbox = cs_dir / "incident_outbox.jsonl"
        if outbox.exists():
            outbox.unlink()

        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.is_success = False
            mock_post.return_value = mock_resp
            result = svc.dispatch(
                {"step_id": "O4", "status": "anomaly", "event_type": "payment.anomaly"}
            )

        incident_result = [r for r in result.get("results", []) if r.get("sink") == "incident_bus"]
        assert incident_result[0]["remote"] is False
        assert outbox.is_file()

    def test_incident_remote_post_error_writes_outbox(self, svc, cs_dir, monkeypatch):
        """When remote post raises an error, should write to outbox."""
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")

        outbox = cs_dir / "incident_outbox.jsonl"
        if outbox.exists():
            outbox.unlink()

        with patch("httpx.post", side_effect=RuntimeError("network error")):
            result = svc.dispatch(
                {"step_id": "O4", "status": "anomaly", "event_type": "payment.anomaly"}
            )

        incident_result = [r for r in result.get("results", []) if r.get("sink") == "incident_bus"]
        assert incident_result[0]["remote"] is False
        assert outbox.is_file()

    def test_no_base_url_skips_remote_post(self, svc, cs_dir, monkeypatch):
        """When XCAGI_MARKET_BASE_URL is not set, should skip remote post."""
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)

        outbox = cs_dir / "incident_outbox.jsonl"
        if outbox.exists():
            outbox.unlink()

        result = svc.dispatch(
            {"step_id": "O4", "status": "anomaly", "event_type": "payment.anomaly"}
        )

        incident_result = [r for r in result.get("results", []) if r.get("sink") == "incident_bus"]
        assert incident_result[0]["remote"] is False
        assert outbox.is_file()


# ---------------------------------------------------------------------------
# _post_incident_remote
# ---------------------------------------------------------------------------


class TestPostIncidentRemote:
    def test_no_base_url_returns_false(self, svc, monkeypatch):
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        result = svc._post_incident_remote({"event_type": "test"})
        assert result is False

    def test_empty_base_url_returns_false(self, svc, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "")
        result = svc._post_incident_remote({"event_type": "test"})
        assert result is False

    def test_whitespace_base_url_returns_false(self, svc, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "   ")
        result = svc._post_incident_remote({"event_type": "test"})
        assert result is False

    def test_successful_post_returns_true(self, svc, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_post.return_value = mock_resp
            result = svc._post_incident_remote({"event_type": "test"})
        assert result is True

    def test_failed_post_returns_false(self, svc, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.is_success = False
            mock_post.return_value = mock_resp
            result = svc._post_incident_remote({"event_type": "test"})
        assert result is False

    def test_post_error_returns_false(self, svc, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")
        with patch("httpx.post", side_effect=RuntimeError("network error")):
            result = svc._post_incident_remote({"event_type": "test"})
        assert result is False

    def test_post_value_error_returns_false(self, svc, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")
        with patch("httpx.post", side_effect=ValueError("value error")):
            result = svc._post_incident_remote({"event_type": "test"})
        assert result is False

    def test_base_url_trailing_slash_stripped(self, svc, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com/")
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_post.return_value = mock_resp
            svc._post_incident_remote({"event_type": "test"})
        url = mock_post.call_args[0][0]
        assert url == "https://market.example.com/api/admin/production-line/incident"

    def test_no_secret_no_header(self, svc, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")
        monkeypatch.delenv("XCAGI_OPS_LINE_HOOK_SECRET", raising=False)
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_post.return_value = mock_resp
            svc._post_incident_remote({"event_type": "test"})
        _, kwargs = mock_post.call_args
        assert "X-Ops-Line-Secret" not in kwargs["headers"]

    def test_empty_secret_no_header(self, svc, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")
        monkeypatch.setenv("XCAGI_OPS_LINE_HOOK_SECRET", "")
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_post.return_value = mock_resp
            svc._post_incident_remote({"event_type": "test"})
        _, kwargs = mock_post.call_args
        assert "X-Ops-Line-Secret" not in kwargs["headers"]

    def test_whitespace_secret_no_header(self, svc, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://market.example.com")
        monkeypatch.setenv("XCAGI_OPS_LINE_HOOK_SECRET", "   ")
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_post.return_value = mock_resp
            svc._post_incident_remote({"event_type": "test"})
        _, kwargs = mock_post.call_args
        assert "X-Ops-Line-Secret" not in kwargs["headers"]


# ---------------------------------------------------------------------------
# status_snapshot
# ---------------------------------------------------------------------------


class TestStatusSnapshot:
    def test_snapshot_with_no_recent(self, svc, cs_dir):
        """When there are no recent audits, last_event_at should be None."""
        snap = svc.status_snapshot()
        assert snap["operations_routes"] >= 0
        assert snap["last_event_at"] is None
        assert snap["recent_route_ids"] == []

    def test_snapshot_after_dispatch(self, svc, cs_dir):
        """After dispatching events, snapshot should show recent activity."""
        svc.dispatch({"step_id": "O7", "status": "progress"})
        svc.dispatch({"step_id": "O4", "status": "anomaly", "event_type": "payment.anomaly"})

        snap = svc.status_snapshot()
        assert snap["last_event_at"] is not None
        assert len(snap["recent_route_ids"]) > 0

    def test_snapshot_counts(self, svc):
        snap = svc.status_snapshot()
        assert "operations_routes" in snap
        assert "cross_line_routes" in snap
        assert "incident_defaults" in snap
        assert "digest_backlog_pending" in snap
        assert "incident_pending" in snap
        assert "version" in snap


# ---------------------------------------------------------------------------
# list_backlog_for_digest
# ---------------------------------------------------------------------------


class TestListBacklogForDigest:
    def test_file_not_found_returns_empty(self, svc, cs_dir):
        result = svc.list_backlog_for_digest()
        assert result == []

    def test_empty_file_returns_empty(self, svc, cs_dir):
        backlog = cs_dir / "six_line_digest_backlog.jsonl"
        backlog.write_text("", encoding="utf-8")
        result = svc.list_backlog_for_digest()
        assert result == []

    def test_whitespace_only_file_returns_empty(self, svc, cs_dir):
        backlog = cs_dir / "six_line_digest_backlog.jsonl"
        backlog.write_text("   \n  \n  ", encoding="utf-8")
        result = svc.list_backlog_for_digest()
        assert result == []

    def test_valid_entries_returned(self, svc, cs_dir):
        backlog = cs_dir / "six_line_digest_backlog.jsonl"
        entries = [
            {"route_id": "r1", "step_id": "O7"},
            {"route_id": "r2", "step_id": "O8"},
        ]
        backlog.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
        result = svc.list_backlog_for_digest()
        assert len(result) == 2
        assert result[0]["route_id"] == "r1"
        assert result[1]["route_id"] == "r2"

    def test_invalid_json_lines_skipped(self, svc, cs_dir):
        backlog = cs_dir / "six_line_digest_backlog.jsonl"
        backlog.write_text(
            '{"valid": true}\n{invalid json}\n{"also_valid": true}',
            encoding="utf-8",
        )
        result = svc.list_backlog_for_digest()
        assert len(result) == 2
        assert result[0]["valid"] is True
        assert result[1]["also_valid"] is True

    def test_limit_applied(self, svc, cs_dir):
        backlog = cs_dir / "six_line_digest_backlog.jsonl"
        entries = [{"id": i} for i in range(10)]
        backlog.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
        result = svc.list_backlog_for_digest(limit=3)
        assert len(result) == 3
        # Should return the last 3 entries
        assert result[0]["id"] == 7
        assert result[2]["id"] == 9

    def test_empty_lines_skipped(self, svc, cs_dir):
        backlog = cs_dir / "six_line_digest_backlog.jsonl"
        backlog.write_text(
            '{"valid": true}\n\n\n{"also_valid": true}',
            encoding="utf-8",
        )
        result = svc.list_backlog_for_digest()
        assert len(result) == 2


# ---------------------------------------------------------------------------
# get_six_line_event_app_service
# ---------------------------------------------------------------------------


class TestGetSixLineEventAppService:
    def test_returns_instance(self):
        svc = get_six_line_event_app_service()
        assert isinstance(svc, SixLineEventAppService)

    def test_returns_new_instance_each_call(self):
        svc1 = get_six_line_event_app_service()
        svc2 = get_six_line_event_app_service()
        assert svc1 is not svc2
