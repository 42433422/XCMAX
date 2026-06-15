"""COVERAGE_RAMP Phase 4 round 7: mod_manager scan/load/install deep paths +
planner LLM/critic mock paths.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import app.infrastructure.mods.mod_manager as mm
from app.infrastructure.mods.mod_manager import (
    ModManager,
    _all_mods_roots,
    _backend_path_for_mod,
    import_mod_backend_py,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_mod(root: Path, mod_id: str, extra: dict | None = None) -> Path:
    mod_dir = root / mod_id
    mod_dir.mkdir(parents=True, exist_ok=True)
    data = {"id": mod_id, "name": mod_id.title(), "version": "1.0.0"}
    if extra:
        data.update(extra)
    (mod_dir / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    return mod_dir


@pytest.fixture
def isolated_mods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A ModManager whose only mods root is tmp_path (no repo-layout bleed)."""
    monkeypatch.delenv("XCAGI_MODS_ROOT", raising=False)
    monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
    monkeypatch.delenv("XCAGI_DISABLE_MODS", raising=False)
    monkeypatch.setattr(mm, "_repo_layout_mods_candidates", lambda: [])
    manager = ModManager(mods_root=str(tmp_path))
    return manager, tmp_path


# ---------------------------------------------------------------------------
# module-level helpers
# ---------------------------------------------------------------------------


def test_backend_path_for_mod() -> None:
    assert _backend_path_for_mod("/a/b").endswith(os.path.join("b", "backend"))


def test_all_mods_roots_dedup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_MODS_ROOT", raising=False)
    monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
    monkeypatch.setattr(mm, "_repo_layout_mods_candidates", lambda: [])
    roots = _all_mods_roots(str(tmp_path))
    assert roots == [str(tmp_path)]


def test_all_mods_roots_includes_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(other))
    monkeypatch.setattr(mm, "_repo_layout_mods_candidates", lambda: [])
    roots = _all_mods_roots(str(tmp_path))
    assert str(tmp_path) in roots
    assert str(other) in roots


# ---------------------------------------------------------------------------
# import_mod_backend_py
# ---------------------------------------------------------------------------


def test_import_mod_backend_py_success_and_cache(tmp_path: Path) -> None:
    mod_dir = tmp_path / "mymod"
    backend = mod_dir / "backend"
    backend.mkdir(parents=True)
    (backend / "thing.py").write_text("VALUE = 42\n", encoding="utf-8")
    try:
        m1 = import_mod_backend_py(str(mod_dir), "mymod", "thing")
        assert m1.VALUE == 42
        m2 = import_mod_backend_py(str(mod_dir), "mymod", "thing")
        assert m1 is m2  # cache branch
    finally:
        for k in [k for k in list(sys.modules) if k.startswith("_xcagi_mod_") and "thing" in k]:
            sys.modules.pop(k, None)


def test_import_mod_backend_py_missing_file(tmp_path: Path) -> None:
    mod_dir = tmp_path / "nomod"
    mod_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        import_mod_backend_py(str(mod_dir), "nomod", "ghost")


# ---------------------------------------------------------------------------
# scan_mods / cache / fingerprint
# ---------------------------------------------------------------------------


def test_scan_mods_parses_valid_and_records_invalid(isolated_mods) -> None:
    manager, root = isolated_mods
    _make_mod(root, "alpha")
    _make_mod(root, "beta")
    # invalid: directory with manifest missing id
    bad = root / "broken"
    bad.mkdir()
    (bad / "manifest.json").write_text("{}", encoding="utf-8")
    mods = manager.scan_mods(use_cache=False)
    ids = {m.id for m in mods}
    assert "alpha" in ids and "beta" in ids
    assert any(e["entry"] == "broken" for e in manager.get_scan_manifest_errors())


def test_scan_mods_cache_hit(isolated_mods) -> None:
    manager, root = isolated_mods
    _make_mod(root, "alpha")
    first = manager.scan_mods()
    second = manager.scan_mods()  # served from cache
    assert {m.id for m in first} == {m.id for m in second}
    manager.invalidate_scan_cache()
    assert manager._scan_cache_fp == ""


def test_mods_scan_fingerprint_changes(isolated_mods) -> None:
    manager, root = isolated_mods
    fp_empty = manager._mods_scan_fingerprint()
    _make_mod(root, "alpha")
    fp_one = manager._mods_scan_fingerprint()
    assert fp_empty != fp_one


# ---------------------------------------------------------------------------
# resolve_mod_directory
# ---------------------------------------------------------------------------


def test_resolve_mod_directory_found(isolated_mods) -> None:
    manager, root = isolated_mods
    _make_mod(root, "alpha")
    hit = manager.resolve_mod_directory("alpha")
    assert hit is not None and hit.endswith("alpha")


def test_resolve_mod_directory_missing(isolated_mods) -> None:
    manager, _root = isolated_mods
    assert manager.resolve_mod_directory("does-not-exist") is None
    assert manager.resolve_mod_directory("") is None


# ---------------------------------------------------------------------------
# failure tracking
# ---------------------------------------------------------------------------


def test_failure_tracking(isolated_mods) -> None:
    manager, _root = isolated_mods
    manager._record_load_failure("m1", "fs", "missing")
    manager.record_blueprint_failure("m1", "bp boom")
    assert manager.get_recent_load_failures()[0]["mod_id"] == "m1"
    assert manager.get_blueprint_failures()[0]["message"] == "bp boom"


# ---------------------------------------------------------------------------
# registry-backed getters
# ---------------------------------------------------------------------------


def test_get_mod_and_list_loaded(isolated_mods) -> None:
    manager, _root = isolated_mods
    fake_registry = MagicMock()
    meta = MagicMock()
    fake_registry.get_mod_metadata.return_value = meta
    fake_registry.list_mods.return_value = [meta]
    with patch.object(mm, "get_mod_registry", return_value=fake_registry):
        assert manager.get_mod("x") is meta
        assert manager.list_loaded_mods() == [meta]


def test_metadata_to_api_dict(isolated_mods) -> None:
    manager, root = isolated_mods
    _make_mod(root, "alpha", extra={"author": "me", "primary": True})
    mods = manager.scan_mods(use_cache=False)
    row = manager._metadata_to_api_dict(mods[0])
    assert row["id"] == "alpha"
    assert row["primary"] is True
    assert "menu" in row and "workflow_employees" in row


# ---------------------------------------------------------------------------
# list_all_mods / get_routes (with entitlement passthrough)
# ---------------------------------------------------------------------------


def test_list_all_mods_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_DISABLE_MODS", "1")
    manager = ModManager(mods_root="/tmp/whatever")
    assert manager.list_all_mods() == []


def test_get_routes_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_DISABLE_MODS", "true")
    manager = ModManager(mods_root="/tmp/whatever")
    assert manager.get_routes() == []


# ---------------------------------------------------------------------------
# install / uninstall error branches
# ---------------------------------------------------------------------------


def test_install_mod_package_signature_error(isolated_mods) -> None:
    manager, _root = isolated_mods
    from app.infrastructure.mods.package import ModSignatureError

    with patch.object(
        mm.ModPackage,
        "extract_package",
        side_effect=ModSignatureError("bad sig"),
    ):
        ok, msg, meta = manager.install_mod_package("/tmp/pkg.xcmod")
    assert ok is False
    assert "签名" in msg
    assert meta is None


def test_install_mod_package_invalid_package(isolated_mods) -> None:
    manager, _root = isolated_mods
    from app.infrastructure.mods.package import ModPackageError

    with patch.object(
        mm.ModPackage,
        "extract_package",
        side_effect=ModPackageError("corrupt"),
    ):
        ok, msg, meta = manager.install_mod_package("/tmp/pkg.xcmod")
    assert ok is False
    assert "无效" in msg


def test_uninstall_mod_not_found(isolated_mods) -> None:
    manager, _root = isolated_mods
    fake_registry = MagicMock()
    fake_registry.get_mod_metadata.return_value = None
    fake_er = MagicMock()
    fake_er._root.return_value = "/nonexistent_root"
    with (
        patch.object(mm, "get_mod_registry", return_value=fake_registry),
        patch(
            "app.infrastructure.mods.employee_registry.get_employee_registry",
            return_value=fake_er,
        ),
    ):
        ok, msg = manager.uninstall_mod("ghost")
    assert ok is False
    assert "未加载或不存在" in msg


# ---------------------------------------------------------------------------
# Planner LLM / critic mock paths
# ---------------------------------------------------------------------------


def _make_planner():
    from app.application.workflow.planner import LLMWorkflowPlanner

    planner = LLMWorkflowPlanner()
    ai = MagicMock()
    ai.api_key = "sk-test"
    ai.api_url = "http://llm.test/v1/chat/completions"
    ai.model = "deepseek-chat"
    ai.get_context.return_value = None
    planner._ai_service = ai
    return planner


_TOOL_REGISTRY = {
    "products": {
        "description": "产品工具",
        "actions": {
            "query": {"risk": "low", "idempotent": True, "required_params": []},
        },
    }
}


def _llm_response(content: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def test_plan_with_llm_success() -> None:
    planner = _make_planner()
    plan_json = json.dumps(
        {
            "intent": "查询产品",
            "todo_steps": ["查询产品"],
            "risk_level": "low",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": "products",
                    "action": "query",
                    "params": {"keyword": "9803"},
                    "risk": "low",
                    "idempotent": True,
                    "description": "查询",
                    "depends_on": [],
                }
            ],
        }
    )
    client = MagicMock()
    client.post.return_value = _llm_response("```json\n" + plan_json + "\n```")
    with patch(
        "app.application.workflow.planner._get_planner_http_client",
        return_value=client,
    ):
        plan = planner._plan_with_llm("pid", "u1", "查 9803", _TOOL_REGISTRY, {})
    assert plan is not None
    assert len(plan.nodes) == 1
    assert plan.nodes[0].tool_id == "products"
    assert plan.metadata.get("planner") == "llm"


def test_plan_with_llm_no_api_key() -> None:
    planner = _make_planner()
    planner._ai_service.api_key = ""
    plan = planner._plan_with_llm("pid", "u1", "msg", _TOOL_REGISTRY, {})
    assert plan is None


def test_plan_with_llm_http_error() -> None:
    planner = _make_planner()
    client = MagicMock()
    client.post.return_value = _llm_response("{}", status=500)
    with patch(
        "app.application.workflow.planner._get_planner_http_client",
        return_value=client,
    ):
        plan = planner._plan_with_llm("pid", "u1", "msg", _TOOL_REGISTRY, {})
    assert plan is None


def test_plan_with_llm_empty_content() -> None:
    planner = _make_planner()
    client = MagicMock()
    client.post.return_value = _llm_response("")
    with patch(
        "app.application.workflow.planner._get_planner_http_client",
        return_value=client,
    ):
        plan = planner._plan_with_llm("pid", "u1", "msg", _TOOL_REGISTRY, {})
    assert plan is None


def test_critic_repair_no_api_key() -> None:
    from app.application.workflow.planner import PlanGraph

    planner = _make_planner()
    planner._ai_service.api_key = ""
    invalid = PlanGraph(plan_id="p", intent="x", todo_steps=[], nodes=[], risk_level="low")
    out = planner._critic_repair_with_llm(
        "p", "u1", "msg", _TOOL_REGISTRY, {}, "err", invalid
    )
    assert out is None
