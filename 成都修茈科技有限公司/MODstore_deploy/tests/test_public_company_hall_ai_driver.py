from __future__ import annotations


def test_public_ai_driver_snapshot_is_live_and_secret_safe(tmp_path, monkeypatch):
    from modstore_server import llm_runtime_autopilot, llm_runtime_route, services
    from modstore_server.public_company_hall import _public_ai_driver_snapshot

    monkeypatch.setattr(
        llm_runtime_route,
        "current_runtime_route",
        lambda: {
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "switched_at": "2026-07-22T08:00:00+00:00",
            "reason": "secret internal reason",
        },
    )
    monkeypatch.setattr(
        services.llm,
        "resolve_platform_bench_llm",
        lambda: ("minimax", "MiniMax-M2.7"),
    )
    monkeypatch.setattr(
        llm_runtime_autopilot,
        "autopilot_status",
        lambda: {
            "enabled": True,
            "ledger_path": str(tmp_path / "must-not-leak.jsonl"),
            "last_run": {
                "checked_at": "2026-07-22T08:05:00+00:00",
                "action": "switched",
                "reason": "contains sk-must-not-leak",
                "quota": {
                    "minimax": {
                        "state": "healthy",
                        "visibility": "exact",
                        "remaining_percent": 99,
                    }
                },
            },
        },
    )

    snapshot = _public_ai_driver_snapshot()

    assert snapshot["state"] == "driving"
    assert snapshot["state_label"] == "自动驾驶中"
    assert snapshot["provider"] == "minimax"
    assert snapshot["model"] == "MiniMax-M2.7"
    assert snapshot["quota"]["remaining_percent"] == 99
    assert "ledger_path" not in snapshot
    assert "reason" not in snapshot
    assert "sk-must-not-leak" not in str(snapshot)
