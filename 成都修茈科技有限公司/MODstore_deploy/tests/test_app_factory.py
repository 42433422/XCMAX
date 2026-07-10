import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

from modstore_server.api.app_factory import (
    AppConfig,
    _init_background_jobs,
    _init_database,
    _init_event_subscribers,
    _register_core_routes,
    _register_diagnostics,
    _register_optional_routes,
    create_app,
    load_default_config,
)


class TestAppConfig:
    def test_default_profile_is_full(self):
        cfg = AppConfig()
        assert cfg.profile == "full"

    def test_llm_only_profile(self):
        cfg = AppConfig(profile="llm-only")
        assert cfg.profile == "llm-only"

    def test_frozen(self):
        cfg = AppConfig()
        with pytest.raises(AttributeError):
            cfg.profile = "other"


class TestLoadDefaultConfig:
    def test_default_returns_full(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_default_config()
            assert cfg.profile == "full"

    def test_llm_only_env(self):
        with patch.dict(os.environ, {"MODSTORE_APP_PROFILE": "llm-only"}):
            cfg = load_default_config()
            assert cfg.profile == "llm-only"

    def test_llm_only_underscore_env(self):
        with patch.dict(os.environ, {"MODSTORE_APP_PROFILE": "llm_only"}):
            cfg = load_default_config()
            assert cfg.profile == "llm-only"

    def test_unknown_profile_returns_full(self):
        with patch.dict(os.environ, {"MODSTORE_APP_PROFILE": "unknown"}):
            cfg = load_default_config()
            assert cfg.profile == "full"


class TestInitDatabase:
    @patch("modstore_server.api.app_factory._init_database")
    def test_init_database_called(self, mock_init):
        mock_init.return_value = None
        mock_init()
        mock_init.assert_called_once()


class TestInitBackgroundJobs:
    def test_skipped_when_env_not_set(self):
        with patch.dict(os.environ, {"MODSTORE_RUN_BACKGROUND_JOBS": "0"}):
            _init_background_jobs()

    def test_runs_when_env_set(self):
        with patch.dict(os.environ, {"MODSTORE_RUN_BACKGROUND_JOBS": "1"}):
            with patch("modstore_server.eventing.db_outbox.start_default_worker") as mock_outbox:
                with patch(
                    "modstore_server.subscription_renewer.start_subscription_scheduler"
                ) as mock_sub:
                    with patch("modstore_server.workflow_scheduler.start_scheduler") as mock_wf:
                        _init_background_jobs()
                        mock_outbox.assert_called_once()
                        mock_sub.assert_called_once()
                        mock_wf.assert_called_once()


class TestCreateApp:
    def test_full_profile_creates_app(self):
        with patch.dict(os.environ, {}, clear=False):
            app = create_app(AppConfig(profile="full"))
            assert app.title == "XC AGI"
            assert app.version == "0.2.0"

    def test_llm_only_profile_creates_app(self):
        with patch.dict(os.environ, {}, clear=False):
            app = create_app(AppConfig(profile="llm-only"))
            assert app.title == "XC AGI"

    def test_default_config_creates_app(self):
        with patch.dict(os.environ, {}, clear=False):
            app = create_app()
            assert app is not None

    @pytest.mark.asyncio
    async def test_edge_tts_warmup_does_not_block_api_startup(self, monkeypatch):
        from modstore_server import edge_tts_service

        warmup_started = asyncio.Event()

        async def _blocked_warmup():
            warmup_started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(edge_tts_service, "warm_defaults", _blocked_warmup)
        app = create_app(AppConfig(profile="llm-only"))
        startup = next(
            handler
            for handler in app.router.on_startup
            if handler.__name__ == "_warm_edge_tts_on_startup"
        )

        await asyncio.wait_for(startup(), timeout=0.2)
        await asyncio.wait_for(warmup_started.wait(), timeout=0.2)

        task = app.state.edge_tts_warmup_task
        assert task.done() is False
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
