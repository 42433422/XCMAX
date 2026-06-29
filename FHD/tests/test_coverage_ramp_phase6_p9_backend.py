"""COVERAGE_RAMP Phase 6 round 9: backend low-coverage modules.

Targets:
- ``app/mod_sdk/planner_tools.py`` (59.9% line coverage, 83 uncovered lines)
- ``app/neuro_bus/domains/shipment_domain_handlers.py`` (30.3% line coverage, 83 uncovered lines)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB / external
API / mod manager / workflow registry). The handler functions themselves are
exercised through real calls.

Coverage scenarios per 铁律3:
- Happy path (valid input)
- Empty / None input
- Boundary values (empty list, empty dict)
- Exception paths (RECOVERABLE_ERRORS: RuntimeError, ValueError, etc.)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.mod_sdk import planner_tools
from app.mod_sdk.planner_tools import (
    PLANNER_FACADE_MOD_ID,
    _manifest_tools_execution_enabled,
    _read_planner_manifest,
    _resolve_planner_mod_dir,
    _truthy_env,
    execute_planner_tool_from_body,
    execute_planner_workflow_tool,
    get_planner_chat_tool_registry,
    is_planner_mod_installed,
    is_planner_mod_on_disk,
    is_planner_tools_via_mod_enabled,
    list_planner_tools_registry_detail,
    load_mod_planner_tool_extensions,
    load_planner_tools_config,
    resolve_planner_tool_executor,
)
from app.neuro_bus.domains.shipment_domain_handlers import (
    ShipmentDomainHandlers,
    get_shipment_domain_handlers,
    register_shipment_domain_handlers,
)

# ---------------------------------------------------------------------------
# planner_tools — _truthy_env
# ---------------------------------------------------------------------------


def test_truthy_env_true_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for val in ("1", "true", "TRUE", "True", "yes", "Yes", "on", "ON"):
        monkeypatch.setenv("X_TEST_ENV", val)
        assert _truthy_env("X_TEST_ENV") is True


def test_truthy_env_false_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for val in ("0", "false", "no", "off", "", "  ", "random"):
        monkeypatch.setenv("X_TEST_ENV", val)
        assert _truthy_env("X_TEST_ENV") is False


def test_truthy_env_unset_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X_TEST_ENV_UNSET", raising=False)
    assert _truthy_env("X_TEST_ENV_UNSET") is False


# ---------------------------------------------------------------------------
# planner_tools — _resolve_planner_mod_dir (manager path + env fallback)
# ---------------------------------------------------------------------------


def test_resolve_planner_mod_dir_manager_hit(tmp_path: Path) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    mod_dir.mkdir()
    (mod_dir / "manifest.json").write_text("{}", encoding="utf-8")

    mock_meta = MagicMock()
    mock_meta.mod_path = str(mod_dir)
    mock_mgr = MagicMock()
    mock_mgr.get_mod.return_value = mock_meta

    with patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        return_value=mock_mgr,
    ):
        result = _resolve_planner_mod_dir()
    assert result == mod_dir


def test_resolve_planner_mod_dir_manager_returns_none_falls_through_to_repo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # manager returns None → 走 env / repo fallback；repo_mods 存在 → 返回 repo 路径
    monkeypatch.delenv("XCAGI_MODS_ROOT", raising=False)
    monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
    fake_module = tmp_path / "FHD" / "app" / "mod_sdk" / "planner_tools.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("", encoding="utf-8")
    repo_mod = tmp_path / "FHD" / "mods" / PLANNER_FACADE_MOD_ID
    repo_mod.mkdir(parents=True)
    (repo_mod / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(planner_tools, "__file__", str(fake_module))

    mock_mgr = MagicMock()
    mock_mgr.get_mod.return_value = None

    # mods_dir() 也返回 None
    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ),
        patch("app.shell.xcagi_mods_discover.mods_dir", return_value=None),
    ):
        result = _resolve_planner_mod_dir()
    assert result == repo_mod


def test_resolve_planner_mod_dir_all_paths_miss_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 切换 cwd 到空目录，且让 repo_mods 不存在 manifest
    monkeypatch.delenv("XCAGI_MODS_ROOT", raising=False)
    monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    mock_mgr = MagicMock()
    mock_mgr.get_mod.return_value = None

    # 让 mods_dir 返回一个不存在的路径
    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ),
        patch("app.shell.xcagi_mods_discover.mods_dir", return_value=str(tmp_path)),
        # 让 repo_mods 的 manifest.json 检查失败
        patch("pathlib.Path.is_file", return_value=False),
    ):
        result = _resolve_planner_mod_dir()
    assert result is None


def test_resolve_planner_mod_dir_manager_raises_recoverable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XCAGI_MODS_ROOT", raising=False)
    monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    def _raise() -> None:
        raise RuntimeError("mod manager down")

    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=_raise,
        ),
        patch("app.shell.xcagi_mods_discover.mods_dir", return_value=None),
        patch("pathlib.Path.is_file", return_value=False),
    ):
        result = _resolve_planner_mod_dir()
    assert result is None


def test_resolve_planner_mod_dir_env_root_hit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    mod_dir.mkdir()
    (mod_dir / "manifest.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
    monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)

    mock_mgr = MagicMock()
    mock_mgr.get_mod.return_value = None

    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ),
        patch("app.shell.xcagi_mods_discover.mods_dir", return_value=None),
    ):
        result = _resolve_planner_mod_dir()
    assert result == mod_dir


def test_resolve_planner_mod_dir_dedup_seen_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # XCAGI_MODS_ROOT 与 XCAGI_MODS_DIR 指向同一目录 → 只检查一次
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    mod_dir.mkdir()
    (mod_dir / "manifest.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_MODS_DIR", str(tmp_path))

    mock_mgr = MagicMock()
    mock_mgr.get_mod.return_value = None

    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ),
        patch("app.shell.xcagi_mods_discover.mods_dir", return_value=None),
    ):
        result = _resolve_planner_mod_dir()
    assert result == mod_dir


# ---------------------------------------------------------------------------
# planner_tools — _read_planner_manifest
# ---------------------------------------------------------------------------


def test_read_planner_manifest_no_mod_dir_returns_empty() -> None:
    with patch("app.mod_sdk.planner_tools._resolve_planner_mod_dir", return_value=None):
        assert _read_planner_manifest() == {}


def test_read_planner_manifest_valid_json(tmp_path: Path) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    mod_dir.mkdir()
    (mod_dir / "manifest.json").write_text(
        json.dumps({"id": PLANNER_FACADE_MOD_ID, "config": {"x": 1}}),
        encoding="utf-8",
    )
    with patch("app.mod_sdk.planner_tools._resolve_planner_mod_dir", return_value=mod_dir):
        out = _read_planner_manifest()
    assert out["id"] == PLANNER_FACADE_MOD_ID
    assert out["config"]["x"] == 1


def test_read_planner_manifest_non_dict_returns_empty(tmp_path: Path) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    mod_dir.mkdir()
    (mod_dir / "manifest.json").write_text("[1, 2, 3]", encoding="utf-8")
    with patch("app.mod_sdk.planner_tools._resolve_planner_mod_dir", return_value=mod_dir):
        assert _read_planner_manifest() == {}


def test_read_planner_manifest_recoverable_error_returns_empty(
    tmp_path: Path,
) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    mod_dir.mkdir()
    (mod_dir / "manifest.json").write_text("not-json", encoding="utf-8")
    with patch("app.mod_sdk.planner_tools._resolve_planner_mod_dir", return_value=mod_dir):
        assert _read_planner_manifest() == {}


# ---------------------------------------------------------------------------
# planner_tools — is_planner_mod_on_disk / is_planner_mod_installed
# ---------------------------------------------------------------------------


def test_is_planner_mod_on_disk_true() -> None:
    with patch(
        "app.mod_sdk.planner_tools._resolve_planner_mod_dir",
        return_value=Path("/tmp/some"),
    ):
        assert is_planner_mod_on_disk() is True


def test_is_planner_mod_on_disk_false() -> None:
    with patch("app.mod_sdk.planner_tools._resolve_planner_mod_dir", return_value=None):
        assert is_planner_mod_on_disk() is False


def test_is_planner_mod_installed_mods_disabled_returns_false() -> None:
    with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
        assert is_planner_mod_installed() is False


def test_is_planner_mod_installed_list_all_mods_hit() -> None:
    mock_mgr = MagicMock()
    mock_mgr.list_all_mods.return_value = [
        {"id": "other-mod"},
        {"id": PLANNER_FACADE_MOD_ID},
    ]
    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ),
    ):
        assert is_planner_mod_installed() is True


def test_is_planner_mod_installed_list_all_mods_miss_falls_to_disk() -> None:
    mock_mgr = MagicMock()
    mock_mgr.list_all_mods.return_value = [{"id": "other"}]
    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ),
        patch("app.mod_sdk.planner_tools.is_planner_mod_on_disk", return_value=True),
    ):
        assert is_planner_mod_installed() is True


def test_is_planner_mod_installed_list_all_mods_raises_recoverable() -> None:
    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=RuntimeError("boom"),
        ),
        patch("app.mod_sdk.planner_tools.is_planner_mod_on_disk", return_value=False),
    ):
        assert is_planner_mod_installed() is False


def test_is_planner_mod_installed_is_mods_disabled_raises_recoverable() -> None:
    # is_mods_disabled 抛错 → 走 list_all_mods 路径
    mock_mgr = MagicMock()
    mock_mgr.list_all_mods.return_value = [{"id": PLANNER_FACADE_MOD_ID}]
    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            side_effect=RuntimeError("disabled check fail"),
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mgr,
        ),
    ):
        assert is_planner_mod_installed() is True


# ---------------------------------------------------------------------------
# planner_tools — _manifest_tools_execution_enabled
# ---------------------------------------------------------------------------


def test_manifest_tools_execution_enabled_top_level_true() -> None:
    with patch(
        "app.mod_sdk.planner_tools._read_planner_manifest",
        return_value={"config": {"planner_tools_execution": True}},
    ):
        assert _manifest_tools_execution_enabled() is True


def test_manifest_tools_execution_enabled_nested_via_mod_facade() -> None:
    with patch(
        "app.mod_sdk.planner_tools._read_planner_manifest",
        return_value={"config": {"planner_tools": {"execution_via_mod_facade": True}}},
    ):
        assert _manifest_tools_execution_enabled() is True


def test_manifest_tools_execution_enabled_config_not_dict() -> None:
    with patch(
        "app.mod_sdk.planner_tools._read_planner_manifest",
        return_value={"config": "not-a-dict"},
    ):
        assert _manifest_tools_execution_enabled() is False


def test_manifest_tools_execution_enabled_no_config() -> None:
    with patch("app.mod_sdk.planner_tools._read_planner_manifest", return_value={}):
        assert _manifest_tools_execution_enabled() is False


def test_manifest_tools_execution_enabled_planner_tools_not_dict() -> None:
    with patch(
        "app.mod_sdk.planner_tools._read_planner_manifest",
        return_value={"config": {"planner_tools": "not-a-dict"}},
    ):
        assert _manifest_tools_execution_enabled() is False


def test_manifest_tools_execution_enabled_false_flags() -> None:
    with patch(
        "app.mod_sdk.planner_tools._read_planner_manifest",
        return_value={
            "config": {
                "planner_tools_execution": False,
                "planner_tools": {"execution_via_mod_facade": False},
            }
        },
    ):
        assert _manifest_tools_execution_enabled() is False


# ---------------------------------------------------------------------------
# planner_tools — is_planner_tools_via_mod_enabled
# ---------------------------------------------------------------------------


def test_is_planner_tools_via_mod_enabled_disable_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", "1")
    monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)
    assert is_planner_tools_via_mod_enabled() is False


def test_is_planner_tools_via_mod_enabled_force_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
    monkeypatch.setenv("XCAGI_PLANNER_TOOLS_VIA_MOD", "true")
    assert is_planner_tools_via_mod_enabled() is True


def test_is_planner_tools_via_mod_enabled_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
    monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)
    with patch("app.mod_sdk.planner_tools.is_planner_mod_installed", return_value=False):
        assert is_planner_tools_via_mod_enabled() is False


def test_is_planner_tools_via_mod_enabled_installed_manifest_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
    monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)
    with (
        patch("app.mod_sdk.planner_tools.is_planner_mod_installed", return_value=True),
        patch(
            "app.mod_sdk.planner_tools._manifest_tools_execution_enabled",
            return_value=True,
        ),
    ):
        assert is_planner_tools_via_mod_enabled() is True


def test_is_planner_tools_via_mod_enabled_installed_manifest_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
    monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)
    with (
        patch("app.mod_sdk.planner_tools.is_planner_mod_installed", return_value=True),
        patch(
            "app.mod_sdk.planner_tools._manifest_tools_execution_enabled",
            return_value=False,
        ),
    ):
        assert is_planner_tools_via_mod_enabled() is False


# ---------------------------------------------------------------------------
# planner_tools — load_planner_tools_config
# ---------------------------------------------------------------------------


def test_load_planner_tools_config_no_mod_dir() -> None:
    with patch("app.mod_sdk.planner_tools._resolve_planner_mod_dir", return_value=None):
        assert load_planner_tools_config() == {}


def test_load_planner_tools_config_no_file(tmp_path: Path) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    mod_dir.mkdir()
    with patch("app.mod_sdk.planner_tools._resolve_planner_mod_dir", return_value=mod_dir):
        assert load_planner_tools_config() == {}


def test_load_planner_tools_config_valid(tmp_path: Path) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    cfg_dir = mod_dir / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "planner_tools.json").write_text(
        json.dumps({"execution": {"via_mod": True}}), encoding="utf-8"
    )
    with patch("app.mod_sdk.planner_tools._resolve_planner_mod_dir", return_value=mod_dir):
        out = load_planner_tools_config()
    assert out["execution"]["via_mod"] is True


def test_load_planner_tools_config_non_dict_returns_empty(tmp_path: Path) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    cfg_dir = mod_dir / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "planner_tools.json").write_text("[1,2,3]", encoding="utf-8")
    with patch("app.mod_sdk.planner_tools._resolve_planner_mod_dir", return_value=mod_dir):
        assert load_planner_tools_config() == {}


def test_load_planner_tools_config_recoverable_error(tmp_path: Path) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    cfg_dir = mod_dir / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "planner_tools.json").write_text("not-json", encoding="utf-8")
    with patch("app.mod_sdk.planner_tools._resolve_planner_mod_dir", return_value=mod_dir):
        assert load_planner_tools_config() == {}


# ---------------------------------------------------------------------------
# planner_tools — load_mod_planner_tool_extensions
# ---------------------------------------------------------------------------


def test_load_mod_planner_tool_extensions_inline_list() -> None:
    inline = [{"function": {"name": "t1"}}, "not-dict", {"function": {"name": "t2"}}]
    with patch(
        "app.mod_sdk.planner_tools._read_planner_manifest",
        return_value={"config": {"planner_tool_extensions": inline}},
    ):
        out = load_mod_planner_tool_extensions()
    assert out == [{"function": {"name": "t1"}}, {"function": {"name": "t2"}}]


def test_load_mod_planner_tool_extensions_inline_not_list() -> None:
    with (
        patch(
            "app.mod_sdk.planner_tools._read_planner_manifest",
            return_value={"config": {"planner_tool_extensions": "not-list"}},
        ),
        patch("app.mod_sdk.planner_tools._resolve_planner_mod_dir", return_value=None),
    ):
        assert load_mod_planner_tool_extensions() == []


def test_load_mod_planner_tool_extensions_file_list(tmp_path: Path) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    cfg_dir = mod_dir / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "planner_tool_extensions.json").write_text(
        json.dumps([{"function": {"name": "ext1"}}]), encoding="utf-8"
    )
    with (
        patch(
            "app.mod_sdk.planner_tools._read_planner_manifest",
            return_value={"config": {}},
        ),
        patch(
            "app.mod_sdk.planner_tools._resolve_planner_mod_dir",
            return_value=mod_dir,
        ),
    ):
        out = load_mod_planner_tool_extensions()
    assert out == [{"function": {"name": "ext1"}}]


def test_load_mod_planner_tool_extensions_file_dict_with_tools(tmp_path: Path) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    cfg_dir = mod_dir / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "planner_tool_extensions.json").write_text(
        json.dumps({"tools": [{"function": {"name": "ext2"}}]}), encoding="utf-8"
    )
    with (
        patch(
            "app.mod_sdk.planner_tools._read_planner_manifest",
            return_value={"config": {}},
        ),
        patch(
            "app.mod_sdk.planner_tools._resolve_planner_mod_dir",
            return_value=mod_dir,
        ),
    ):
        out = load_mod_planner_tool_extensions()
    assert out == [{"function": {"name": "ext2"}}]


def test_load_mod_planner_tool_extensions_file_not_exist(tmp_path: Path) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    mod_dir.mkdir()
    with (
        patch(
            "app.mod_sdk.planner_tools._read_planner_manifest",
            return_value={"config": {}},
        ),
        patch(
            "app.mod_sdk.planner_tools._resolve_planner_mod_dir",
            return_value=mod_dir,
        ),
    ):
        assert load_mod_planner_tool_extensions() == []


def test_load_mod_planner_tool_extensions_file_recoverable_error(
    tmp_path: Path,
) -> None:
    mod_dir = tmp_path / PLANNER_FACADE_MOD_ID
    cfg_dir = mod_dir / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "planner_tool_extensions.json").write_text("bad-json", encoding="utf-8")
    with (
        patch(
            "app.mod_sdk.planner_tools._read_planner_manifest",
            return_value={"config": {}},
        ),
        patch(
            "app.mod_sdk.planner_tools._resolve_planner_mod_dir",
            return_value=mod_dir,
        ),
    ):
        assert load_mod_planner_tool_extensions() == []


def test_load_mod_planner_tool_extensions_no_mod_dir() -> None:
    with (
        patch(
            "app.mod_sdk.planner_tools._read_planner_manifest",
            return_value={"config": {}},
        ),
        patch("app.mod_sdk.planner_tools._resolve_planner_mod_dir", return_value=None),
    ):
        assert load_mod_planner_tool_extensions() == []


# ---------------------------------------------------------------------------
# planner_tools — get_planner_chat_tool_registry
# ---------------------------------------------------------------------------


def test_get_planner_chat_tool_registry_no_extensions() -> None:
    base_reg = [{"function": {"name": "tool_a"}}, {"function": {"name": "tool_b"}}]
    with (
        patch(
            "app.application.tools.workflow.get_workflow_tool_registry",
            return_value=base_reg,
        ),
        patch(
            "app.mod_sdk.planner_tools.load_mod_planner_tool_extensions",
            return_value=[],
        ),
    ):
        out = get_planner_chat_tool_registry()
    assert out == base_reg


def test_get_planner_chat_tool_registry_with_extensions() -> None:
    base_reg = [{"function": {"name": "tool_a"}}]
    ext = [{"function": {"name": "ext_tool"}}]
    with (
        patch(
            "app.application.tools.workflow.get_workflow_tool_registry",
            return_value=base_reg,
        ),
        patch(
            "app.mod_sdk.planner_tools.load_mod_planner_tool_extensions",
            return_value=ext,
        ),
    ):
        out = get_planner_chat_tool_registry()
    assert out == [{"function": {"name": "tool_a"}}, {"function": {"name": "ext_tool"}}]


# ---------------------------------------------------------------------------
# planner_tools — resolve_planner_tool_executor
# ---------------------------------------------------------------------------


def test_resolve_planner_tool_executor_via_mod_enabled() -> None:
    with patch(
        "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
        return_value=True,
    ):
        fn = resolve_planner_tool_executor()
    assert fn is execute_planner_workflow_tool


def test_resolve_planner_tool_executor_via_host_workflow() -> None:
    mock_host = MagicMock()
    with (
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=False,
        ),
        patch("app.application.tools.workflow.execute_workflow_tool", mock_host),
    ):
        fn = resolve_planner_tool_executor()
    assert fn is mock_host


# ---------------------------------------------------------------------------
# planner_tools — execute_planner_workflow_tool
# ---------------------------------------------------------------------------


def test_execute_planner_workflow_tool_native_hit() -> None:
    native_raw = '{"success": true, "source": "mod:xcagi-planner-excel-tools"}'
    with patch(
        "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
        return_value=(native_raw, "xcagi-planner-excel-tools"),
    ):
        out = execute_planner_workflow_tool("excel_tool", {"x": 1})
    assert out == native_raw


def test_execute_planner_workflow_tool_employee_pack_hit() -> None:
    emp_raw = '{"success": true, "source": "employee_pack"}'
    with (
        patch(
            "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
            return_value=(None, None),
        ),
        patch(
            "app.application.employee_pack_runner.try_execute_employee_planner_tool",
            return_value=emp_raw,
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=False,
        ),
    ):
        out = execute_planner_workflow_tool("emp_tool", {})
    assert out == emp_raw


def test_execute_planner_workflow_tool_employee_pack_raises_skips_to_host() -> None:
    host_raw = '{"success": true, "source": "host"}'
    with (
        patch(
            "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
            return_value=(None, None),
        ),
        patch(
            "app.application.employee_pack_runner.try_execute_employee_planner_tool",
            side_effect=RuntimeError("emp runner down"),
        ),
        patch(
            "app.application.tools.workflow.execute_workflow_tool",
            return_value=host_raw,
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=False,
        ),
    ):
        out = execute_planner_workflow_tool("host_tool", {})
    assert out == host_raw


def test_execute_planner_workflow_tool_falls_to_host_workflow() -> None:
    host_raw = '{"success": true}'
    with (
        patch(
            "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
            return_value=(None, None),
        ),
        patch(
            "app.application.employee_pack_runner.try_execute_employee_planner_tool",
            return_value=None,
        ),
        patch(
            "app.application.tools.workflow.execute_workflow_tool",
            return_value=host_raw,
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=True,
        ),
    ):
        out = execute_planner_workflow_tool(
            "host_tool", {"a": 1}, workspace_root="/tmp", db_write_token="tok"
        )
    assert out == host_raw


# ---------------------------------------------------------------------------
# planner_tools — execute_planner_tool_from_body
# ---------------------------------------------------------------------------


def test_execute_planner_tool_from_body_none_body_returns_error() -> None:
    out = execute_planner_tool_from_body(None)
    assert out["success"] is False
    assert out["error"] == "tool_name required"


def test_execute_planner_tool_from_body_empty_body_returns_error() -> None:
    out = execute_planner_tool_from_body({})
    assert out["success"] is False
    assert out["error"] == "tool_name required"


def test_execute_planner_tool_from_body_no_name_returns_error() -> None:
    out = execute_planner_tool_from_body({"tool_name": "   "})
    assert out["success"] is False
    assert out["error"] == "tool_name required"


def test_execute_planner_tool_from_body_name_from_name_field() -> None:
    raw = '{"success": true}'
    mock_exec = MagicMock(return_value=raw)
    with (
        patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
            return_value=mock_exec,
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=False,
        ),
    ):
        out = execute_planner_tool_from_body({"name": "my_tool", "arguments": {}})
    assert out["success"] is True
    assert out["tool_name"] == "my_tool"
    assert out["result"] == raw
    assert out["execution_path"] == "host.workflow"
    assert out["mod_id"] is None
    assert out["delegate"] == "host.workflow"


def test_execute_planner_tool_from_body_mod_native_path() -> None:
    raw = '{"success": true, "source": "mod:xcagi-planner-excel-tools"}'
    mock_exec = MagicMock(return_value=raw)
    with (
        patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
            return_value=mock_exec,
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=True,
        ),
    ):
        out = execute_planner_tool_from_body(
            {"tool_name": "excel", "args": {}, "db_write_token": 123}
        )
    assert out["success"] is True
    assert out["execution_path"] == "mod_native"
    assert out["mod_id"] == "xcagi-planner-excel-tools"
    assert out["delegate"] is None


def test_execute_planner_tool_from_body_mod_facade_path() -> None:
    raw = '{"success": true}'  # 无 source 字段
    mock_exec = MagicMock(return_value=raw)
    with (
        patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
            return_value=mock_exec,
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=True,
        ),
    ):
        out = execute_planner_tool_from_body({"tool_name": "tool_x"})
    assert out["success"] is True
    assert out["execution_path"] == "mod_facade"
    assert out["mod_id"] == PLANNER_FACADE_MOD_ID
    assert out["delegate"] == "host.workflow"


def test_execute_planner_tool_from_body_recoverable_error() -> None:
    mock_exec = MagicMock(side_effect=RuntimeError("exec boom"))
    with (
        patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
            return_value=mock_exec,
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=False,
        ),
    ):
        out = execute_planner_tool_from_body({"tool_name": "fail_tool"})
    assert out["success"] is False
    assert "exec boom" in out["error"]
    assert out["tool_name"] == "fail_tool"


def test_execute_planner_tool_from_body_invalid_json_result() -> None:
    raw = "not-json"
    mock_exec = MagicMock(return_value=raw)
    with (
        patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
            return_value=mock_exec,
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=False,
        ),
    ):
        out = execute_planner_tool_from_body({"tool_name": "tool_y"})
    assert out["success"] is True
    assert out["execution_path"] == "host.workflow"


def test_execute_planner_tool_from_body_workspace_root_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = '{"success": true}'
    mock_exec = MagicMock(return_value=raw)
    monkeypatch.setenv("WORKSPACE_ROOT", "/custom/ws")
    with (
        patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
            return_value=mock_exec,
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=False,
        ),
    ):
        execute_planner_tool_from_body({"tool_name": "tool_z"})
    # workspace_root 应来自 env
    assert mock_exec.call_args.args[2] == "/custom/ws"


# ---------------------------------------------------------------------------
# planner_tools — list_planner_tools_registry_detail
# ---------------------------------------------------------------------------


def test_list_planner_tools_registry_detail_via_mod_disabled() -> None:
    base_reg = [{"function": {"name": "tool_a"}}, {"not_function": True}, {}]
    with (
        patch(
            "app.mod_sdk.planner_tools.get_planner_chat_tool_registry",
            return_value=base_reg,
        ),
        patch(
            "app.mod_sdk.planner_tools.load_mod_planner_tool_extensions",
            return_value=[{"function": {"name": "ext1"}}, {"no_fn": True}],
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=False,
        ),
        patch(
            "app.mod_sdk.planner_tools.load_planner_tools_config",
            return_value={"execution": {"flag": True}},
        ),
        patch(
            "app.mod_sdk.planner_native_tools.list_native_planner_tools_summary",
            return_value={"enabled": False, "tool_names": []},
        ),
        patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"employee_pack_tools": ["emp_tool"]},
        ),
    ):
        out = list_planner_tools_registry_detail()
    assert out["success"] is True
    assert out["tool_count"] == 1
    assert out["tool_names"] == ["tool_a"]
    assert out["mod_extension_count"] == 1
    assert out["mod_extension_names"] == ["ext1"]
    assert out["execution_via_mod_facade"] is False
    assert out["execution_path"] == "host.workflow"
    assert out["mod_id"] is None
    assert out["tools_execute_endpoint"] is None
    assert out["source"] == "host.workflow_tool_registry"
    assert out["delegate"] == "host.workflow"
    assert out["planner_tools_config"] == {"flag": True}
    assert out["employee_pack_tools"] == ["emp_tool"]
    assert "未启用" in out["note"]


def test_list_planner_tools_registry_detail_via_mod_enabled_native_off() -> None:
    with (
        patch(
            "app.mod_sdk.planner_tools.get_planner_chat_tool_registry",
            return_value=[],
        ),
        patch(
            "app.mod_sdk.planner_tools.load_mod_planner_tool_extensions",
            return_value=[],
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=True,
        ),
        patch(
            "app.mod_sdk.planner_tools.load_planner_tools_config",
            return_value={},
        ),
        patch(
            "app.mod_sdk.planner_native_tools.list_native_planner_tools_summary",
            return_value={"enabled": False, "tool_names": []},
        ),
        patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            side_effect=RuntimeError("emp status fail"),
        ),
    ):
        out = list_planner_tools_registry_detail()
    assert out["success"] is True
    assert out["execution_via_mod_facade"] is True
    assert out["execution_path"] == "mod_facade"
    assert out["mod_id"] == PLANNER_FACADE_MOD_ID
    assert out["employee_planner"] == {}
    assert out["employee_pack_tools"] == []
    assert "里程碑 B" in out["note"]


def test_list_planner_tools_registry_detail_native_enabled() -> None:
    with (
        patch(
            "app.mod_sdk.planner_tools.get_planner_chat_tool_registry",
            return_value=[],
        ),
        patch(
            "app.mod_sdk.planner_tools.load_mod_planner_tool_extensions",
            return_value=[],
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=True,
        ),
        patch(
            "app.mod_sdk.planner_tools.load_planner_tools_config",
            return_value=None,
        ),
        patch(
            "app.mod_sdk.planner_native_tools.list_native_planner_tools_summary",
            return_value={"enabled": True, "tool_names": ["excel_tool"]},
        ),
        patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={},
        ),
    ):
        out = list_planner_tools_registry_detail()
    assert out["execution_path"] == "mod_facade+native"
    assert "里程碑 F3" in out["note"]
    assert out["planner_tools_config"] == {}


def test_list_planner_tools_registry_detail_native_only_no_mod_facade() -> None:
    with (
        patch(
            "app.mod_sdk.planner_tools.get_planner_chat_tool_registry",
            return_value=[],
        ),
        patch(
            "app.mod_sdk.planner_tools.load_mod_planner_tool_extensions",
            return_value=[],
        ),
        patch(
            "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
            return_value=False,
        ),
        patch(
            "app.mod_sdk.planner_tools.load_planner_tools_config",
            return_value={},
        ),
        patch(
            "app.mod_sdk.planner_native_tools.list_native_planner_tools_summary",
            return_value={"enabled": True, "tool_names": ["excel_tool"]},
        ),
        patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={},
        ),
    ):
        out = list_planner_tools_registry_detail()
    assert out["execution_path"] == "mod_native"


# ---------------------------------------------------------------------------
# shipment_domain_handlers — handle_shipment_created
# ---------------------------------------------------------------------------


def _make_event(payload: dict[str, Any]) -> MagicMock:
    ev = MagicMock()
    ev.payload = payload
    return ev


@pytest.fixture
def handlers() -> ShipmentDomainHandlers:
    return ShipmentDomainHandlers()


@pytest.mark.asyncio
async def test_handle_shipment_created_happy_path(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event(
        {
            "shipment_id": "S1",
            "unit_name": "甲公司",
            "items": [{"product_id": "P1", "quantity": 2}],
            "contact_person": "张三",
            "contact_phone": "13800000000",
        }
    )
    expected = {"success": True, "shipment_id": "S1"}
    mock_core = MagicMock()
    mock_core.create_shipment.return_value = expected
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
        ) as mock_reply,
    ):
        out = await handlers.handle_shipment_created(event)
    assert out == expected
    mock_core.create_shipment.assert_called_once_with(
        unit_name="甲公司",
        items_data=[{"product_id": "P1", "quantity": 2}],
        contact_person="张三",
        contact_phone="13800000000",
    )
    mock_reply.assert_called_once_with(event, expected)


@pytest.mark.asyncio
async def test_handle_shipment_created_empty_payload(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({})
    expected = {"success": True, "shipment_id": None}
    mock_core = MagicMock()
    mock_core.create_shipment.return_value = expected
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch("app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"),
    ):
        out = await handlers.handle_shipment_created(event)
    assert out == expected
    # 空字段应被规范化为空字符串/空列表
    mock_core.create_shipment.assert_called_once_with(
        unit_name="", items_data=[], contact_person="", contact_phone=""
    )


@pytest.mark.asyncio
async def test_handle_shipment_created_recoverable_error_propagates(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "S1", "unit_name": "甲"})
    mock_core = MagicMock()
    mock_core.create_shipment.side_effect = RuntimeError("db down")
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
        ) as mock_reply,
    ):
        with pytest.raises(RuntimeError, match="db down"):
            await handlers.handle_shipment_created(event)
    mock_reply.assert_called_once()
    # 第二个参数应为 None（result），第三个为 error
    assert mock_reply.call_args.args[1] is None


# ---------------------------------------------------------------------------
# shipment_domain_handlers — handle_item_added
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_item_added_happy_path(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event(
        {
            "shipment_id": "S1",
            "product_id": "P1",
            "quantity": 3,
            "unit_price": 100,
        }
    )
    out = await handlers.handle_item_added(event)
    assert out["success"] is True
    assert out["shipment_id"] == "S1"
    assert out["actions"] == ["item_logged"]
    assert out["amount_delta"] == 300


@pytest.mark.asyncio
async def test_handle_item_added_empty_payload(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({})
    out = await handlers.handle_item_added(event)
    assert out["success"] is True
    assert out["shipment_id"] is None
    assert out["amount_delta"] == 0  # 0 * 0


@pytest.mark.asyncio
async def test_handle_item_added_default_price_qty(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "S2", "product_id": "P2"})
    out = await handlers.handle_item_added(event)
    assert out["amount_delta"] == 0


@pytest.mark.asyncio
async def test_handle_item_added_recoverable_error_in_try_block(
    handlers: ShipmentDomainHandlers,
) -> None:
    # try 块内：price * qty 若触发 LookupError（属于 RECOVERABLE_ERRORS）应被捕获
    # 调用顺序：logger.info(3次) → result init(1次) → try 块 unit_price(第5次)
    event = MagicMock()
    call_count = {"n": 0}

    def _get(key: str, default: object = None) -> object:
        call_count["n"] += 1
        # 前 4 次在 try 块外（logger.info + result init）
        if call_count["n"] <= 4:
            return "val"
        # 第 5 次起是 try 块中的 unit_price → 抛错
        raise LookupError("unit_price missing")

    event.payload.get.side_effect = _get
    out = await handlers.handle_item_added(event)
    assert out["success"] is False
    assert "unit_price missing" in out["error"]


@pytest.mark.asyncio
async def test_handle_item_added_logger_error_propagates(
    handlers: ShipmentDomainHandlers,
) -> None:
    # logger.info 在 try 块外，若 payload.get 抛错应直接传播
    event = MagicMock()
    event.payload.get.side_effect = LookupError("logger key missing")
    with pytest.raises(LookupError, match="logger key missing"):
        await handlers.handle_item_added(event)


# ---------------------------------------------------------------------------
# shipment_domain_handlers — handle_printed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_printed_happy_path(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "42", "printer_name": "HP-LaserJet"})
    expected = {"success": True, "printed": True}
    mock_core = MagicMock()
    mock_core.mark_as_printed.return_value = expected
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
        ) as mock_reply,
    ):
        out = await handlers.handle_printed(event)
    assert out == expected
    mock_core.mark_as_printed.assert_called_once_with(42, "HP-LaserJet")
    mock_reply.assert_called_once_with(event, expected)


@pytest.mark.asyncio
async def test_handle_printed_default_printer_name(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "10"})
    expected = {"success": True}
    mock_core = MagicMock()
    mock_core.mark_as_printed.return_value = expected
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch("app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"),
    ):
        out = await handlers.handle_printed(event)
    assert out == expected
    # printer_name 缺失 → 空字符串
    mock_core.mark_as_printed.assert_called_once_with(10, "")


@pytest.mark.asyncio
async def test_handle_printed_invalid_shipment_id_raises(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "not-an-int"})
    mock_core = MagicMock()
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
        ) as mock_reply,
    ):
        # int("not-an-int") 抛 ValueError（属于 RECOVERABLE_ERRORS）
        with pytest.raises(ValueError):
            await handlers.handle_printed(event)
    mock_core.mark_as_printed.assert_not_called()
    mock_reply.assert_called_once()
    assert mock_reply.call_args.args[1] is None


@pytest.mark.asyncio
async def test_handle_printed_core_raises_recoverable(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "1", "printer_name": "p"})
    mock_core = MagicMock()
    mock_core.mark_as_printed.side_effect = RuntimeError("printer offline")
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
        ) as mock_reply,
    ):
        with pytest.raises(RuntimeError, match="printer offline"):
            await handlers.handle_printed(event)
    mock_reply.assert_called_once()
    assert mock_reply.call_args.args[1] is None


# ---------------------------------------------------------------------------
# shipment_domain_handlers — handle_cancelled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_cancelled_happy_path(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "5", "reason": "客户取消"})
    expected = {"success": True, "cancelled": True}
    mock_core = MagicMock()
    mock_core.cancel_shipment.return_value = expected
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
        ) as mock_reply,
    ):
        out = await handlers.handle_cancelled(event)
    assert out == expected
    mock_core.cancel_shipment.assert_called_once_with(5)
    mock_reply.assert_called_once_with(event, expected)


@pytest.mark.asyncio
async def test_handle_cancelled_default_reason(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "7"})
    expected = {"success": True}
    mock_core = MagicMock()
    mock_core.cancel_shipment.return_value = expected
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch("app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"),
    ):
        out = await handlers.handle_cancelled(event)
    assert out == expected


@pytest.mark.asyncio
async def test_handle_cancelled_invalid_shipment_id_raises(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": None})
    mock_core = MagicMock()
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
        ) as mock_reply,
    ):
        # int(None) 抛 TypeError（不属于 RECOVERABLE_ERRORS？TypeError 不在列表中）
        # 实际：RECOVERABLE_ERRORS = INFRA_TRANSIENT + DATA_SHAPE
        # DATA_SHAPE = (ValueError, json.JSONDecodeError, UnicodeError, LookupError)
        # TypeError 不在其中 → 应该向上抛出
        with pytest.raises(TypeError):
            await handlers.handle_cancelled(event)
    mock_core.cancel_shipment.assert_not_called()


@pytest.mark.asyncio
async def test_handle_cancelled_core_raises_recoverable(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "1"})
    mock_core = MagicMock()
    mock_core.cancel_shipment.side_effect = ValueError("already cancelled")
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
        ) as mock_reply,
    ):
        with pytest.raises(ValueError, match="already cancelled"):
            await handlers.handle_cancelled(event)
    mock_reply.assert_called_once()
    assert mock_reply.call_args.args[1] is None


# ---------------------------------------------------------------------------
# shipment_domain_handlers — handle_deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_deleted_happy_path(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "99"})
    expected = {"success": True, "deleted": True}
    mock_core = MagicMock()
    mock_core.delete_shipment.return_value = expected
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
        ) as mock_reply,
    ):
        out = await handlers.handle_deleted(event)
    assert out == expected
    mock_core.delete_shipment.assert_called_once_with(99)
    mock_reply.assert_called_once_with(event, expected)


@pytest.mark.asyncio
async def test_handle_deleted_invalid_shipment_id_raises(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "abc"})
    mock_core = MagicMock()
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
        ) as mock_reply,
    ):
        with pytest.raises(ValueError):
            await handlers.handle_deleted(event)
    mock_core.delete_shipment.assert_not_called()
    mock_reply.assert_called_once()


@pytest.mark.asyncio
async def test_handle_deleted_core_raises_recoverable(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "1"})
    mock_core = MagicMock()
    mock_core.delete_shipment.side_effect = RuntimeError("db locked")
    with (
        patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core",
            return_value=mock_core,
        ),
        patch("app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"),
    ):
        with pytest.raises(RuntimeError, match="db locked"):
            await handlers.handle_deleted(event)


# ---------------------------------------------------------------------------
# shipment_domain_handlers — handle_exported
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_exported_happy_path(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"file_path": "/tmp/export.xlsx", "record_count": 100})
    out = await handlers.handle_exported(event)
    assert out["success"] is True
    assert out["file_path"] == "/tmp/export.xlsx"
    assert out["actions"] == ["export_logged", "export_stats_updated"]


@pytest.mark.asyncio
async def test_handle_exported_empty_payload(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({})
    out = await handlers.handle_exported(event)
    assert out["success"] is True
    assert out["file_path"] is None
    assert out["actions"] == ["export_logged", "export_stats_updated"]


@pytest.mark.asyncio
async def test_handle_exported_default_record_count(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"file_path": "/tmp/x.xlsx"})
    out = await handlers.handle_exported(event)
    assert out["success"] is True


@pytest.mark.asyncio
async def test_handle_exported_recoverable_error_in_try_block(
    handlers: ShipmentDomainHandlers,
) -> None:
    # logger.info 与 result 初始化在 try 块外，try 块内只有 append 操作
    # 通过让 payload.get 在前 2 次（logger）返回值，第 3 次（result init）返回值，
    # 第 4 次（try 内 actions.append 不会调用 get）→ 实际 try 块内不调用 get
    # 因此 try 块内的 RECOVERABLE_ERRORS 分支难以触发。
    # 改为测试 logger.info 抛错时直接传播（LookupError 属于 RECOVERABLE_ERRORS 但在 try 外）
    event = MagicMock()
    event.payload.get.side_effect = LookupError("file_path missing")
    with pytest.raises(LookupError, match="file_path missing"):
        await handlers.handle_exported(event)


# ---------------------------------------------------------------------------
# shipment_domain_handlers — handle_inventory_deducted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_inventory_deducted_happy_path(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event(
        {
            "shipment_id": "S1",
            "items": [
                {"product_id": "P1", "quantity": 2},
                {"product_id": "P2", "quantity": 5},
            ],
        }
    )
    out = await handlers.handle_inventory_deducted(event)
    assert out["success"] is True
    assert out["shipment_id"] == "S1"
    assert out["actions"] == [
        "inventory_deducted",
        "inventory_movement_logged",
        "alert_checked",
    ]


@pytest.mark.asyncio
async def test_handle_inventory_deducted_empty_items(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "S2", "items": []})
    out = await handlers.handle_inventory_deducted(event)
    assert out["success"] is True
    assert out["actions"] == [
        "inventory_deducted",
        "inventory_movement_logged",
        "alert_checked",
    ]


@pytest.mark.asyncio
async def test_handle_inventory_deducted_missing_items_key(
    handlers: ShipmentDomainHandlers,
) -> None:
    event = _make_event({"shipment_id": "S3"})
    out = await handlers.handle_inventory_deducted(event)
    assert out["success"] is True
    # items 缺失 → 默认 []
    assert out["actions"] == [
        "inventory_deducted",
        "inventory_movement_logged",
        "alert_checked",
    ]


@pytest.mark.asyncio
async def test_handle_inventory_deducted_recoverable_error_propagates(
    handlers: ShipmentDomainHandlers,
) -> None:
    # logger.info 与 result 初始化在 try 块外，若 payload.get 抛错应直接传播
    event = MagicMock()
    event.payload.get.side_effect = LookupError("items missing")
    with pytest.raises(LookupError, match="items missing"):
        await handlers.handle_inventory_deducted(event)


# ---------------------------------------------------------------------------
# shipment_domain_handlers — bus property lazy init
# ---------------------------------------------------------------------------


def test_shipment_handlers_bus_lazy_init() -> None:
    h = ShipmentDomainHandlers()
    assert h._bus is None
    mock_bus = MagicMock()
    with patch(
        "app.neuro_bus.domains.shipment_domain_handlers.get_neuro_bus",
        return_value=mock_bus,
    ):
        assert h.bus is mock_bus
    # 第二次访问应使用缓存
    assert h.bus is mock_bus


# ---------------------------------------------------------------------------
# shipment_domain_handlers — singleton & register
# ---------------------------------------------------------------------------


def test_get_shipment_domain_handlers_singleton() -> None:
    # 重置模块级单例
    import app.neuro_bus.domains.shipment_domain_handlers as mod

    mod._shipment_handlers = None
    a = get_shipment_domain_handlers()
    b = get_shipment_domain_handlers()
    assert a is b
    # 清理以避免污染其他测试
    mod._shipment_handlers = None


def test_register_shipment_domain_handlers_subscribes_all() -> None:
    mock_bus = MagicMock()
    register_shipment_domain_handlers(mock_bus)
    # 应注册 7 个事件
    assert mock_bus.subscribe.call_count == 7
    subscribed_events = [call.args[0] for call in mock_bus.subscribe.call_args_list]
    assert set(subscribed_events) == {
        "shipment.created",
        "shipment.item_added",
        "shipment.printed",
        "shipment.cancelled",
        "shipment.deleted",
        "shipment.exported",
        "shipment.inventory_deducted",
    }
    # 清理单例
    import app.neuro_bus.domains.shipment_domain_handlers as mod

    mod._shipment_handlers = None
