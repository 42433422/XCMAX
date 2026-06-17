"""Tests for app.shell.mod_database_gate — database mod gate logic."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.shell.mod_database_gate import _required_mod_ids, _enabled_mod_ids, mod_db_gate_state, mod_db_gate_open


class TestRequiredModIds:
    def test_empty_env_returns_empty_list(self):
        with patch.dict(os.environ, {"FHD_DB_MOD_GATE": ""}, clear=False):
            result = _required_mod_ids()
        assert result == []

    def test_no_env_returns_empty_list(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove the key entirely
            os.environ.pop("FHD_DB_MOD_GATE", None)
            result = _required_mod_ids()
        assert result == []

    def test_single_mod_id(self):
        with patch.dict(os.environ, {"FHD_DB_MOD_GATE": "mod-a"}, clear=False):
            result = _required_mod_ids()
        assert result == ["mod-a"]

    def test_multiple_comma_separated(self):
        with patch.dict(os.environ, {"FHD_DB_MOD_GATE": "mod-a,mod-b,mod-c"}, clear=False):
            result = _required_mod_ids()
        assert result == ["mod-a", "mod-b", "mod-c"]

    def test_semicolon_separated(self):
        with patch.dict(os.environ, {"FHD_DB_MOD_GATE": "mod-a;mod-b"}, clear=False):
            result = _required_mod_ids()
        assert result == ["mod-a", "mod-b"]

    def test_whitespace_stripped(self):
        with patch.dict(os.environ, {"FHD_DB_MOD_GATE": " mod-a , mod-b "}, clear=False):
            result = _required_mod_ids()
        assert result == ["mod-a", "mod-b"]


class TestEnabledModIds:
    def test_empty_env_returns_empty_set(self):
        with patch.dict(os.environ, {"FHD_ENABLED_MOD_IDS": ""}, clear=False):
            result = _enabled_mod_ids()
        assert result == set()

    def test_single_mod(self):
        with patch.dict(os.environ, {"FHD_ENABLED_MOD_IDS": "mod-a"}, clear=False):
            result = _enabled_mod_ids()
        assert result == {"mod-a"}

    def test_multiple_comma_separated(self):
        with patch.dict(os.environ, {"FHD_ENABLED_MOD_IDS": "mod-a,mod-b"}, clear=False):
            result = _enabled_mod_ids()
        assert result == {"mod-a", "mod-b"}

    def test_semicolon_separated(self):
        with patch.dict(os.environ, {"FHD_ENABLED_MOD_IDS": "mod-a;mod-b"}, clear=False):
            result = _enabled_mod_ids()
        assert result == {"mod-a", "mod-b"}


class TestModDbGateState:
    def test_gate_open_when_no_requirement(self):
        with patch.dict(os.environ, {"FHD_DB_MOD_GATE": ""}, clear=False):
            result = mod_db_gate_state()
        assert result["gate_open"] is True
        assert result["required_mod_ids"] == []

    def test_gate_closed_when_missing_mod(self):
        with patch.dict(os.environ, {"FHD_DB_MOD_GATE": "mod-x", "FHD_ENABLED_MOD_IDS": ""}, clear=False):
            result = mod_db_gate_state()
        assert result["gate_open"] is False
        assert "mod-x" in result["missing_mod_ids"]
        assert "reason" in result

    def test_gate_open_when_all_mods_enabled(self):
        with patch.dict(
            os.environ,
            {"FHD_DB_MOD_GATE": "mod-a,mod-b", "FHD_ENABLED_MOD_IDS": "mod-a,mod-b"},
            clear=False,
        ):
            result = mod_db_gate_state()
        assert result["gate_open"] is True
        assert result["required_mod_ids"] == ["mod-a", "mod-b"]

    def test_gate_closed_partial_missing(self):
        with patch.dict(
            os.environ,
            {"FHD_DB_MOD_GATE": "mod-a,mod-b", "FHD_ENABLED_MOD_IDS": "mod-a"},
            clear=False,
        ):
            result = mod_db_gate_state()
        assert result["gate_open"] is False
        assert result["missing_mod_ids"] == ["mod-b"]


class TestModDbGateOpen:
    def test_open_when_no_requirement(self):
        with patch.dict(os.environ, {"FHD_DB_MOD_GATE": ""}, clear=False):
            assert mod_db_gate_open() is True

    def test_closed_when_missing(self):
        with patch.dict(os.environ, {"FHD_DB_MOD_GATE": "missing-mod", "FHD_ENABLED_MOD_IDS": ""}, clear=False):
            assert mod_db_gate_open() is False

    def test_open_when_satisfied(self):
        with patch.dict(
            os.environ,
            {"FHD_DB_MOD_GATE": "mod-a", "FHD_ENABLED_MOD_IDS": "mod-a"},
            clear=False,
        ):
            assert mod_db_gate_open() is True
