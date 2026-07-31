from __future__ import annotations

from app.utils.agent_route_status import (
    agent_route_http_status,
    restore_agent_domain_error,
)


def test_agent_route_http_status_preserves_success_and_direct_domain_status() -> None:
    assert agent_route_http_status({"success": True}) == 200
    assert agent_route_http_status({"success": False, "http_status_code": 503}) == 503
    assert agent_route_http_status({"success": False, "status_code": "404"}) == 404


def test_agent_route_http_status_reads_semantic_verification_raw_output() -> None:
    assert (
        agent_route_http_status(
            {
                "success": False,
                "error_code": "semantic_verification_failed",
                "raw_output": {"success": False, "http_status_code": 503},
            }
        )
        == 503
    )
    assert (
        agent_route_http_status(
            {
                "success": False,
                "error_code": "semantic_verification_failed",
                "raw_output": {"success": False, "error_code": "tool_exception"},
            }
        )
        == 500
    )


def test_agent_route_http_status_uses_configured_defaults_for_untyped_failures() -> None:
    payload = {"success": False, "status_code": "not-a-number"}
    assert agent_route_http_status(payload) == 400
    assert agent_route_http_status(payload, failure_status=200) == 200
    assert agent_route_http_status({"success": True}, success_status=201) == 201


def test_restore_agent_domain_error_keeps_agent_evidence() -> None:
    payload = {
        "success": False,
        "error_code": "semantic_verification_failed",
        "raw_output": {
            "success": False,
            "error_code": "dataset_permission_denied",
            "message": "dataset.read permission is required",
        },
        "run_id": "run-1",
        "agent_run_id": "run-1",
        "agent_status": "failed",
        "verification": {"accepted": False},
    }

    restored = restore_agent_domain_error(payload)

    assert restored["error_code"] == "dataset_permission_denied"
    assert restored["agent_verification_error_code"] == "semantic_verification_failed"
    assert restored["run_id"] == "run-1"
    assert restored["verification"] == {"accepted": False}


def test_restore_agent_domain_error_leaves_other_payloads_unchanged() -> None:
    ordinary = {"success": False, "error_code": "tool_exception"}
    malformed = {
        "success": False,
        "error_code": "semantic_verification_failed",
        "raw_output": {"success": True},
    }

    assert restore_agent_domain_error(ordinary) is ordinary
    assert restore_agent_domain_error(malformed) is malformed
