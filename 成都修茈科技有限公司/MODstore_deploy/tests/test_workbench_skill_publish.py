"""测试工作台 ``/api/workbench/vibe-code-skill`` 的端到端 NL → publish 闭环。

不打真实 LLM:用 monkeypatch 截获 ``get_vibe_coder``,模拟 vibe-coding 的产出。
不真发 catalog:用 monkeypatch 截获 ``append_package``。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

if importlib.util.find_spec("vibe_coding") is None:
    pytest.skip("vibe-coding 未安装,跳过 workbench publish 测试", allow_module_level=True)


def _stub_skill_with_run() -> SimpleNamespace:
    skill = SimpleNamespace(skill_id="vc-test-publish", code="def fn(): return 42")
    skill.to_dict = lambda: {"skill_id": skill.skill_id, "code": skill.code}
    return skill


class _StubRun:
    def to_dict(self) -> Dict[str, Any]:
        return {"output": 42, "ok": True}


class _StubCoder:
    def __init__(self):
        self.code_store = SimpleNamespace(
            get_code_skill=lambda sid: _stub_skill_with_run() if sid == "vc-test-publish" else None
        )

    def code(self, brief, *, mode="brief_first", skill_id=None, project_root=None, **kwargs):
        return _stub_skill_with_run()

    def run(self, sid, payload):
        assert payload == {"x": 1}
        return _StubRun()


def test_workbench_vibe_code_skill_dry_run(monkeypatch, client, auth_headers):
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_llm_provider_model_auto",
        _async_returning(("openai", "gpt-4o-mini", None)),
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_vibe_coder",
        lambda **kw: _StubCoder(),
    )
    monkeypatch.setattr(
        "modstore_server.workbench_api.get_session_factory",
        lambda: __import__(
            "modstore_server.models", fromlist=["get_session_factory"]
        ).get_session_factory(),
    )

    r = client.post(
        "/api/workbench/vibe-code-skill",
        headers=auth_headers,
        json={"brief": "返回 42", "run_input": {"x": 1}, "dry_run": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["skill"]["skill_id"] == "vc-test-publish"
    assert body["run"]["output"] == 42
    assert body["publish"] is None


def test_workbench_vibe_code_skill_publish(tmp_path, monkeypatch, client, auth_headers):
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_llm_provider_model_auto",
        _async_returning(("openai", "gpt-4o-mini", None)),
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_vibe_coder",
        lambda **kw: _StubCoder(),
    )

    fake_zip = tmp_path / "vc-published.xcmod"
    fake_zip.write_bytes(b"PK\x03\x04stub")

    class _StubArtifact:
        archive_path = str(fake_zip)

        def to_dict(self):
            return {"archive_path": str(fake_zip), "pkg_id": "vc-test-publish"}

    class _StubPackager:
        def __init__(self):
            pass

        def package_skill(self, skill, *, options, siblings=None):
            return _StubArtifact()

    monkeypatch.setattr("vibe_coding.agent.marketplace.SkillPackager", _StubPackager, raising=False)
    monkeypatch.setattr(
        "modstore_server.catalog_store.append_package",
        lambda rec, p: {
            "version": rec["version"],
            "name": rec["name"],
            "description": rec["description"],
            "industry": rec["industry"],
            "stored_filename": Path(p).name,
            "sha256": "fake-sha",
        },
    )

    r = client.post(
        "/api/workbench/vibe-code-skill",
        headers=auth_headers,
        json={
            "brief": "返回 42",
            "run_input": {"x": 1},
            "dry_run": False,
            "publish": {
                "pkg_id": "vc-test-publish",
                "name": "test publish",
                "description": "stub",
                "price": 0,
                "artifact": "mod",
                "industry": "通用",
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["publish"]["ok"] is True
    assert body["publish"]["pkg_id"] == "vc-test-publish"


def test_workbench_vibe_code_skill_publish_requires_pkg_id(monkeypatch, client, auth_headers):
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_llm_provider_model_auto",
        _async_returning(("openai", "gpt-4o-mini", None)),
    )
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_vibe_coder",
        lambda **kw: _StubCoder(),
    )

    r = client.post(
        "/api/workbench/vibe-code-skill",
        headers=auth_headers,
        json={
            "brief": "返回 42",
            "run_input": {"x": 1},
            "publish": {"pkg_id": ""},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["publish"]["ok"] is False
    assert "pkg_id" in body["publish"]["error"]


def _async_returning(value):
    """生成一个 async 函数,无视参数总是返回 ``value``。"""

    async def _impl(*args, **kwargs):
        return value

    return _impl
