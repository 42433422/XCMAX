# -*- coding: utf-8 -*-

from __future__ import annotations

import json

from app.application.tenant_workspace_prefs import (
    get_workspace_prefs,
    patch_workspace_prefs,
)


def test_patch_workspace_prefs_merges_workflow_employees(monkeypatch):
    store: dict[str, dict[str, str]] = {}

    class FakePrefService:
        def get_preference(self, user_id: str, preference_key: str) -> str | None:
            return store.get(user_id, {}).get(preference_key)

        def set_preference(self, user_id: str, preference_key: str, preference_value: str) -> bool:
            store.setdefault(user_id, {})[preference_key] = preference_value
            return True

    monkeypatch.setattr(
        "app.services.user_preference_service.get_user_preference_service",
        lambda: FakePrefService(),
    )

    owner = "tenant:42"
    patch_workspace_prefs(owner, {"selected_industry_id": "涂料", "industry_mod_id": "coating-industry"})
    patch_workspace_prefs(owner, {"workflow_ai_employees": {"emp-a": True}})
    patch_workspace_prefs(owner, {"workflow_ai_employees": {"emp-b": False}})

    prefs = get_workspace_prefs(owner)
    assert prefs["selected_industry_id"] == "涂料"
    assert prefs["workflow_ai_employees"] == {"emp-a": True, "emp-b": False}

    raw = store[owner]["workspace_prefs"]
    assert json.loads(raw)["industry_mod_id"] == "coating-industry"
