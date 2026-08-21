"""Regression coverage for failures discovered in the installed macOS app."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_clear_missing_local_mod_also_clears_runtime_integrity_issue() -> None:
    from app.infrastructure.mods import missing_local_state

    missing_local_state._MISSING_LOCAL.add("coating-industry")
    with patch("app.runtime_integrity.clear_runtime_issue") as clear_issue:
        missing_local_state.clear_mod_missing_locally("coating-industry")

    assert "coating-industry" not in missing_local_state._MISSING_LOCAL
    clear_issue.assert_called_once_with("industry_mod:coating-industry")


def test_missing_open_industry_mod_is_restored_from_bundled_seed_before_mount() -> None:
    from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

    mm = MagicMock()
    mm._loaded_mods = set()
    mm._http_routes_registered = set()
    mm.resolve_mod_directory.return_value = None

    def seed_industry(mod_id: str) -> dict[str, object]:
        mm._loaded_mods.add(mod_id)
        return {"success": True, "status": "seeded", "mod_id": mod_id}

    with (
        patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
        patch("app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id"),
        patch("app.infrastructure.mods.mod_manager._mod_allowed_for_api_load", return_value=True),
        patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm),
        patch(
            "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
            return_value=["coating-industry"],
        ),
        patch("app.mod_sdk.industry_seed.seed_industry_mod", side_effect=seed_industry) as seed,
        patch("app.infrastructure.mods.mod_manager.clear_mod_missing_locally") as clear_missing,
        patch("app.fastapi_app.get_fastapi_app", return_value="app"),
        patch(
            "app.infrastructure.mods.mod_manager._register_single_mod_http_routes",
            return_value=True,
        ) as register,
    ):
        assert ensure_mod_api_ready("coating-industry", session_id="session") is True

    seed.assert_called_once_with("coating-industry")
    mm.load_mod.assert_not_called()
    clear_missing.assert_called_with("coating-industry")
    register.assert_called_once_with("app", mm, "coating-industry")
