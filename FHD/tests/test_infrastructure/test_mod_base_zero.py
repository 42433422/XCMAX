"""Tests for app.infrastructure.mods.base."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.infrastructure.mods.base import Mod


class ConcreteMod(Mod):
    """Concrete implementation for testing."""

    def init(self) -> bool:
        return True

    def register_routes(self, app: FastAPI) -> None:
        pass


class FailingMod(Mod):
    """Mod that fails initialization."""

    def init(self) -> bool:
        return False

    def register_routes(self, app: FastAPI) -> None:
        pass


class TestMod:
    """Tests for Mod base class."""

    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            Mod()

    def test_concrete_init(self) -> None:
        mod = ConcreteMod()
        assert mod.init() is True

    def test_failing_init(self) -> None:
        mod = FailingMod()
        assert mod.init() is False

    def test_default_cleanup(self) -> None:
        mod = ConcreteMod()
        # Should not raise
        mod.cleanup()

    def test_default_get_hooks(self) -> None:
        mod = ConcreteMod()
        assert mod.get_hooks() == []

    def test_metadata_default_none(self) -> None:
        mod = ConcreteMod()
        assert mod.metadata is None

    def test_register_routes(self) -> None:
        app = FastAPI()
        mod = ConcreteMod()
        mod.register_routes(app)
        # Should not raise

    def test_custom_hooks(self) -> None:
        class HookMod(Mod):
            def init(self) -> bool:
                return True

            def register_routes(self, app: FastAPI) -> None:
                pass

            def get_hooks(self) -> list[str]:
                return ["on_startup", "on_shutdown"]

        mod = HookMod()
        assert mod.get_hooks() == ["on_startup", "on_shutdown"]

    def test_custom_cleanup(self) -> None:
        class CleanupMod(Mod):
            cleaned = False

            def init(self) -> bool:
                return True

            def register_routes(self, app: FastAPI) -> None:
                pass

            def cleanup(self) -> None:
                CleanupMod.cleaned = True

        mod = CleanupMod()
        mod.cleanup()
        assert CleanupMod.cleaned is True
