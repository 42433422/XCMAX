"""Deterministic Para delivery_validation extraction + timeout classification."""

from __future__ import annotations

from modstore_server.self_maintenance_loop_runner import (
    _find_delivery_validation,
    _is_accepted_para_wait_timeout,
)


def test_find_delivery_validation_nested_preferred_path():
    nested = {
        "noise": {"other": 1},
        "result": {
            "outputs": [
                {
                    "handler": "para_delegate",
                    "response": {
                        "para_result": {
                            "delivery_validation": {
                                "ok": True,
                                "commands": [{"exit_code": 0}],
                            }
                        }
                    },
                }
            ]
        },
    }
    dv = _find_delivery_validation(nested)
    assert isinstance(dv, dict)
    assert dv.get("ok") is True


def test_is_accepted_para_wait_timeout():
    result = {
        "result": {
            "outputs": [
                {
                    "handler": "para_delegate",
                    "accepted": True,
                    "status": "para_task_timeout",
                }
            ]
        }
    }
    assert _is_accepted_para_wait_timeout(result) is True
    assert _is_accepted_para_wait_timeout({"result": {"outputs": []}}) is False
