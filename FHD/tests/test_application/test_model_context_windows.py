"""Context budgets follow the active model's window instead of a fixed 8000."""

from __future__ import annotations

import pytest

from app.application.agent_orchestrator.context_window_manager import ContextWindowManager
from app.infrastructure.llm import model_context_windows as windows


@pytest.fixture(autouse=True)
def _reset_catalog():
    windows.reset_cache()
    yield
    windows.reset_cache()


def test_known_model_uses_catalog_window():
    assert windows.context_window_for("deepseek-chat") == 65536
    assert windows.context_window_for("gpt-4o") == 128000


def test_unknown_model_falls_back_to_default_window():
    assert windows.context_window_for("not-a-real-model") == 16384


def test_budget_is_half_the_window_with_floor_and_ceiling():
    assert windows.resolve_token_budget("deepseek-chat") == 32000
    assert windows.resolve_token_budget("unknown-small-model") == 8192
    assert windows.resolve_token_budget("deepseek-chat", window=4000) == 8000


def test_missing_catalog_degrades_to_defaults(tmp_path, monkeypatch):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(windows, "_CATALOG_PATH", missing)
    assert windows.load_catalog() == {}
    assert windows.resolve_token_budget("deepseek-chat") == 8192


def test_manager_resolves_budget_from_model_when_not_explicit():
    manager = ContextWindowManager()
    assert manager.budget_for("deepseek-chat") == 32000
    assert manager.budget_for(None) == 8192


def test_manager_keeps_explicit_budget():
    manager = ContextWindowManager(token_budget=900)
    assert manager.budget_for("deepseek-chat") == 900
