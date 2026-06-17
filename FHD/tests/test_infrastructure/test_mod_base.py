"""Tests for app.infrastructure.mods.base."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.infrastructure.mods.base import Mod


class TestMod:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Mod()

    def test_concrete_subclass(self):
        class ConcreteMod(Mod):
            def init(self):
                return True

            def register_routes(self, app):
                pass

        mod = ConcreteMod()
        assert mod.init() is True
        assert mod.get_hooks() == []
        assert mod.metadata is None

    def test_cleanup_default(self):
        class ConcreteMod(Mod):
            def init(self):
                return True

            def register_routes(self, app):
                pass

        mod = ConcreteMod()
        result = mod.cleanup()
        assert result is None

    def test_register_routes_called(self):
        class ConcreteMod(Mod):
            def init(self):
                return True

            def register_routes(self, app):
                app.test_route = True

        mod = ConcreteMod()
        mock_app = MagicMock()
        mod.register_routes(mock_app)
        assert mock_app.test_route is True

    def test_custom_hooks(self):
        class ConcreteMod(Mod):
            def init(self):
                return True

            def register_routes(self, app):
                pass

            def get_hooks(self):
                return ["on_message", "on_login"]

        mod = ConcreteMod()
        assert mod.get_hooks() == ["on_message", "on_login"]
