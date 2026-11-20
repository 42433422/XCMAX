from modstore_server.para_model_admission import platform_model_admission, select_route


def provider(name, remaining, *, visibility="exact", model_remaining=100):
    return {
        "provider": name,
        "visibility": visibility,
        "state": "healthy",
        "resources": [
            {"resource": "general", "remaining_percent": remaining},
            {"resource": "coding", "remaining_percent": model_remaining},
        ],
    }


ROUTES = {
    "para-a": {"provider": "a", "resource": "coding"},
    "para-b": {"provider": "b", "resource": "coding"},
}


def test_uses_both_model_and_provider_limits_when_allocating():
    result = select_route([provider("a", 100, model_remaining=84), provider("b", 92)], ROUTES, 80)
    assert result["model"] == "para-b"
    assert result["headroom_percent"] == 12


def test_waits_if_no_route_is_above_reserve_with_verified_quota():
    result = select_route([provider("a", 80), provider("b", 100, visibility="usage_only")], ROUTES, 80)
    assert result["status"] == "waiting"


def test_invalid_active_policy_leaves_task_waiting(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_PLATFORM_POOL", "1")
    monkeypatch.setenv("MODSTORE_PARA_PLATFORM_ROUTES", "{}")
    assert platform_model_admission()["reason"] == "invalid_platform_policy"
