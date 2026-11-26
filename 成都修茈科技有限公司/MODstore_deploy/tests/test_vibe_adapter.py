"""测试 :mod:`modstore_server.integrations.vibe_adapter`。

只覆盖纯逻辑层(LLMClient 桥接、租户路径白名单、缓存),不打真实 LLM。
当 :mod:`vibe_coding` 不可导入时整体跳过,避免在 CI 环境抹掉信号。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

if importlib.util.find_spec("vibe_coding") is None:
    pytest.skip("vibe-coding 未安装,跳过适配器测试", allow_module_level=True)


def test_chat_dispatch_client_strips_markdown_fence(monkeypatch):
    from modstore_server.integrations.vibe_adapter import ChatDispatchLLMClient

    captured = {}

    async def fake_dispatch(provider, *, api_key, base_url, model, messages, max_tokens=None):
        captured["provider"] = provider
        captured["messages"] = messages
        return {"ok": True, "content": '```json\n{"k": 1}\n```\n'}

    monkeypatch.setattr("modstore_server.llm_chat_proxy.chat_dispatch", fake_dispatch)

    client = ChatDispatchLLMClient("openai", api_key="fake", model="gpt-4o-mini")
    out = client.chat("you are helpful", "produce JSON", json_mode=True)
    assert out == '{"k": 1}'
    assert captured["provider"] == "openai"
    # json_mode=True 会在 system 里追加 JSON 限制
    assert any("只输出一个合法 JSON" in (m.get("content") or "") for m in captured["messages"])


def test_chat_dispatch_client_raises_on_failure(monkeypatch):
    from vibe_coding import LLMError

    from modstore_server.integrations.vibe_adapter import ChatDispatchLLMClient

    async def failing_dispatch(*args, **kwargs):
        return {"ok": False, "error": "boom", "status": 500}

    monkeypatch.setattr("modstore_server.llm_chat_proxy.chat_dispatch", failing_dispatch)

    client = ChatDispatchLLMClient("openai", api_key="fake", model="gpt-4o-mini")
    with pytest.raises(LLMError):
        client.chat("s", "u", json_mode=False)


def test_ensure_within_workspace_rejects_traversal(tmp_path, monkeypatch):
    from modstore_server.integrations.vibe_adapter import (
        VibePathError,
        ensure_within_workspace,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(workspace / "{user_id}"))

    user_root = workspace / "42"
    user_root.mkdir()
    (user_root / "app").mkdir()

    resolved = ensure_within_workspace(user_root / "app", user_id=42)
    assert resolved == (user_root / "app").resolve()

    with pytest.raises(VibePathError):
        ensure_within_workspace(tmp_path / "outside", user_id=42)

    # 越界:试图访问别的用户工作区
    other = workspace / "99"
    other.mkdir()
    with pytest.raises(VibePathError):
        ensure_within_workspace(other, user_id=42)

    sibling = workspace / "420"
    sibling.mkdir()
    link = user_root / "linked"
    link.symlink_to(other, target_is_directory=True)
    for rejected in (sibling, user_root / ".." / "99", link):
        with pytest.raises(VibePathError):
            ensure_within_workspace(rejected, user_id=42)
    link.unlink()
    link.symlink_to(user_root / "app", target_is_directory=True)
    assert ensure_within_workspace(link, user_id=42) == (user_root / "app").resolve()
    assert ensure_within_workspace(user_root, user_id=42) == user_root.resolve()


@pytest.mark.parametrize("outside_name", ["outside", "42-other"])
def test_workspace_rejects_external_path_before_resolving_it(tmp_path, monkeypatch, outside_name):
    from modstore_server.integrations.vibe_adapter import (
        VibePathError,
        ensure_within_workspace,
    )

    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "{user_id}"))
    workspace = tmp_path / "42"
    workspace.mkdir()
    outside = tmp_path / outside_name
    outside.mkdir()
    accessed = []
    realpath = os.path.realpath

    def record_realpath(path, *args, **kwargs):
        accessed.append(os.fspath(path))
        return realpath(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", record_realpath)
    with pytest.raises(VibePathError):
        ensure_within_workspace(outside, user_id=42)
    assert str(outside) not in accessed


def test_workspace_keeps_new_outputs_inside_selected_project(tmp_path, monkeypatch):
    from modstore_server.integrations.vibe_adapter import (
        VibePathError,
        ensure_within_workspace,
    )

    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "{user_id}"))
    project = tmp_path / "42" / "project"
    project.mkdir(parents=True)
    source = project / "source.csv"
    source.write_text("name\nAlice\n", encoding="utf-8")
    assert ensure_within_workspace(source, user_id=42) == source
    assert (
        ensure_within_workspace("new/output.csv", user_id=42, within=project, must_exist=False)
        == project / "new" / "output.csv"
    )
    for path in ("../other/output.csv", tmp_path / "42" / "other" / "output.csv"):
        with pytest.raises(VibePathError):
            ensure_within_workspace(path, user_id=42, within=project, must_exist=False)
    with pytest.raises(VibePathError):
        ensure_within_workspace("new/output.csv", user_id=42, within=project)


def test_workspace_rejects_symlink_escape_for_existing_and_new_paths(tmp_path, monkeypatch):
    from modstore_server.integrations.vibe_adapter import (
        VibePathError,
        ensure_within_workspace,
    )

    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "{user_id}"))
    project = tmp_path / "42"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "source.csv").write_text("private", encoding="utf-8")
    try:
        (project / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    for path, exists in (("link/source.csv", True), ("link/new.csv", False)):
        with pytest.raises(VibePathError):
            ensure_within_workspace(path, user_id=42, within=project, must_exist=exists)


def test_workspace_accepts_trusted_configured_symlink(tmp_path, monkeypatch):
    from modstore_server.integrations.vibe_adapter import ensure_within_workspace

    actual = tmp_path / "actual"
    project = actual / "42" / "project"
    project.mkdir(parents=True)
    source = project / "source.csv"
    source.write_text("content", encoding="utf-8")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(alias / "{user_id}"))
    aliased_project = alias / "42" / "project"
    assert ensure_within_workspace(aliased_project / "source.csv", user_id=42) == source
    selected = ensure_within_workspace(aliased_project, user_id=42)
    assert (
        ensure_within_workspace(
            "new.csv",
            user_id=42,
            within=selected,
            must_exist=False,
        )
        == project / "new.csv"
    )


@pytest.mark.parametrize("escape", ["absolute", "tenant", "prefix", "parent"])
def test_workspace_rejects_escape_before_resolving_user_path(tmp_path, monkeypatch, escape):
    from modstore_server import autonomy_guard_delegate
    from modstore_server.integrations.vibe_adapter import VibePathError, ensure_within_workspace

    platform_locator = Path(autonomy_guard_delegate.__file__).absolute()
    workspace = tmp_path / "workspaces" / "42"
    workspace.mkdir(parents=True)
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(workspace.parent / "{user_id}"))
    targets = {
        "absolute": tmp_path / "private",
        "tenant": workspace.parent / "99",
        "prefix": workspace.parent / "420",
        "parent": workspace / ".." / "99",
    }
    original = os.path.realpath
    probed = []

    def observed(path, *args, **kwargs):
        probed.append(Path(os.path.abspath(path)))
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os.path, "realpath", observed)
        with pytest.raises(VibePathError) as denied:
            ensure_within_workspace(targets[escape], user_id=42)
    # Module and tenant-root guards resolve only fixed, server-selected anchors.
    assert all(
        path in (platform_locator, workspace.parent) or path.is_relative_to(workspace)
        for path in probed
    ), probed
    assert Path(os.path.abspath(targets[escape])) not in probed
    assert str(tmp_path) not in str(denied.value)


def test_workspace_rejects_symlink_escape_before_existence_probe(tmp_path, monkeypatch):
    from modstore_server.integrations.vibe_adapter import VibePathError, ensure_within_workspace

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    link = workspace / "linked-project"
    link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(workspace))
    original = Path.exists
    probed = []

    def observed(path):
        probed.append(path)
        return original(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "exists", observed)
        with pytest.raises(VibePathError) as denied:
            ensure_within_workspace(link, user_id=42)
    assert outside not in probed
    assert str(tmp_path) not in str(denied.value)


def test_workspace_preserves_configured_symlink_and_relative_paths(tmp_path, monkeypatch):
    from modstore_server.integrations.vibe_adapter import ensure_within_workspace

    workspace = tmp_path / "real" / "42"
    project = workspace / "nested" / "project"
    project.mkdir(parents=True)
    configured = tmp_path / "configured"
    configured.symlink_to(workspace.parent, target_is_directory=True)
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(configured / "{user_id}"))
    monkeypatch.chdir(tmp_path)
    assert ensure_within_workspace(configured / "42", user_id=42) == workspace
    assert ensure_within_workspace(configured / "42/nested/project", user_id=42) == project
    assert ensure_within_workspace("configured/42/nested/project", user_id=42) == project
    assert ensure_within_workspace(project, user_id=42) == project


def test_workspace_missing_path_stays_missing_without_exposing_server_path(tmp_path, monkeypatch):
    from modstore_server.integrations.vibe_adapter import VibePathError, ensure_within_workspace

    workspace = tmp_path / "workspace"
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(workspace))
    assert ensure_within_workspace(workspace, user_id=42) == workspace
    missing = workspace / "missing"
    with pytest.raises(VibePathError) as denied:
        ensure_within_workspace(missing, user_id=42)
    assert not missing.exists()
    assert str(tmp_path) not in str(denied.value)


@pytest.mark.parametrize("case", ["tenant", "prefix", "parent"])
def test_workspace_rejects_foreign_paths_before_filesystem_probe(tmp_path, monkeypatch, case):
    from modstore_server.integrations.vibe_adapter import VibePathError, ensure_within_workspace

    workspace = tmp_path / "42"
    workspace.mkdir()
    other = tmp_path / ("42-private" if case == "prefix" else "99")
    other.mkdir()
    foreign = other / "secret.txt"
    foreign.write_text("private")
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "{user_id}"))
    candidate = workspace / ".." / other.name / foreign.name if case == "parent" else foreign
    lstat = os.lstat

    def guarded_lstat(path, *args, **kwargs):
        assert Path(path) != foreign, "foreign path was probed before authorization"
        return lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", guarded_lstat)
    with pytest.raises(VibePathError, match="工作区") as error:
        ensure_within_workspace(candidate, user_id=42)
    assert str(tmp_path) not in str(error.value)


def test_workspace_keeps_cwd_relative_paths_and_inward_links(tmp_path, monkeypatch):
    from modstore_server.integrations.vibe_adapter import VibePathError, ensure_within_workspace

    workspace = tmp_path / "42"
    project = workspace / "project"
    project.mkdir(parents=True)
    (workspace / "link").symlink_to(project, target_is_directory=True)
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "{user_id}"))
    monkeypatch.chdir(tmp_path)

    assert ensure_within_workspace("42/project", user_id=42) == project
    assert ensure_within_workspace(workspace / "link", user_id=42) == project
    with pytest.raises(VibePathError):
        ensure_within_workspace(workspace / "missing", user_id=42)


def test_get_vibe_coder_caches_per_user_provider(monkeypatch, tmp_path):
    from modstore_server.integrations import vibe_adapter

    monkeypatch.setenv("VIBE_CODING_STORE_DIR", str(tmp_path / "vibe-data"))
    vibe_adapter.reset_vibe_coder_cache()

    constructed = []

    class _StubVibeCoder:
        def __init__(self, *, llm, store_dir, **kwargs):
            constructed.append((id(llm), str(store_dir)))
            self.llm = llm
            self.store_dir = Path(store_dir)

    def fake_import_facade():
        return (_StubVibeCoder, object)

    def fake_from_user(session, user_id, provider, model, *, default_max_tokens=4096):
        return object()

    monkeypatch.setattr(vibe_adapter, "_import_facade", fake_import_facade)
    monkeypatch.setattr(
        vibe_adapter.ChatDispatchLLMClient,
        "from_user",
        classmethod(lambda cls, *a, **k: object()),
    )

    c1 = vibe_adapter.get_vibe_coder(user_id=1, provider="openai", model="gpt-4o-mini")
    c2 = vibe_adapter.get_vibe_coder(user_id=1, provider="openai", model="gpt-4o-mini")
    c3 = vibe_adapter.get_vibe_coder(user_id=2, provider="openai", model="gpt-4o-mini")
    c4 = vibe_adapter.get_vibe_coder(user_id=1, provider="deepseek", model="deepseek-chat")

    assert c1 is c2  # 同 user + 同 provider/model => 命中缓存
    assert c1 is not c3
    assert c1 is not c4
    assert len(constructed) == 3


def test_get_vibe_coder_requires_provider_model(monkeypatch):
    from modstore_server.integrations.vibe_adapter import (
        VibeIntegrationError,
        get_vibe_coder,
    )

    with pytest.raises(VibeIntegrationError):
        get_vibe_coder(user_id=1, provider="", model="gpt-4o-mini")
    with pytest.raises(VibeIntegrationError):
        get_vibe_coder(user_id=1, provider="openai", model="")
