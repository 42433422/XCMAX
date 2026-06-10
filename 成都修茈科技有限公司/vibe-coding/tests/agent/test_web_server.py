"""Tests for the FastAPI web server.

Skipped automatically when fastapi / starlette TestClient are missing
(the package keeps fastapi as an optional extra). When they are
available, we exercise the JSON API end-to-end with a stubbed
:class:`VibeCoder` so no real LLM is hit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from vibe_coding.agent.web.server import create_app


@dataclass
class _StubSkill:
    skill_id: str = "demo"

    def to_dict(self) -> dict[str, Any]:
        return {"skill_id": self.skill_id}


@dataclass
class _StubPatch:
    patch_id: str = "p-1"

    def to_dict(self) -> dict[str, Any]:
        return {"patch_id": self.patch_id, "summary": "demo", "edits": []}


@dataclass
class _StubApplyResult:
    patch_id: str = "p-1"
    applied: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"patch_id": self.patch_id, "applied": self.applied}


@dataclass
class _StubIndex:
    summary_data: dict[str, Any] = field(default_factory=lambda: {"files": 3, "symbols": 12})

    def summary(self) -> dict[str, Any]:
        return dict(self.summary_data)


@dataclass
class _StubHeal:
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"success": self.success, "rounds": [], "brief": ""}


@dataclass
class _StubPublish:
    published: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"published": self.published, "skill_id": "demo"}


@dataclass
class _StubCoder:
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def code(self, brief, **kw):
        self.calls.append(("code", brief))
        return _StubSkill()

    def workflow_with_report(self, brief):
        self.calls.append(("workflow", brief))

        @dataclass
        class _R:
            workflow_id: str = "wf-1"
            warnings: list[str] = field(default_factory=list)
            graph: Any = None

            def __post_init__(self) -> None:
                @dataclass
                class _G:
                    def to_dict(self) -> dict[str, Any]:
                        return {"nodes": []}

                self.graph = _G()

        return _R()

    def run(self, skill_id, payload):
        self.calls.append(("run", (skill_id, payload)))

        @dataclass
        class _Run:
            run_id: str = "r-1"

            def to_dict(self) -> dict[str, Any]:
                return {"run_id": self.run_id, "skill_id": skill_id}

        return _Run()

    def index_project(self, root, *, refresh=False):
        self.calls.append(("index", (str(root), refresh)))
        return _StubIndex()

    def edit_project(self, brief, *, root, focus_paths=None, **_):
        self.calls.append(("edit", (brief, str(root))))
        return _StubPatch()

    def apply_patch(self, patch, *, root, dry_run=False):
        self.calls.append(("apply", (patch.patch_id, str(root), dry_run)))
        return _StubApplyResult(patch_id=patch.patch_id)

    def heal_project(self, brief, *, root, max_rounds=3, **_):
        self.calls.append(("heal", (brief, str(root), max_rounds)))
        return _StubHeal()

    def publish_skill(self, skill_id, **kw):
        self.calls.append(("publish", (skill_id, dict(kw))))
        return _StubPublish()


@pytest.fixture
def stub_coder() -> _StubCoder:
    return _StubCoder()


@pytest.fixture
def client(stub_coder: _StubCoder) -> TestClient:
    return TestClient(create_app(coder=stub_coder))


def test_index_html_served(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "vibe-coding" in res.text


def test_health_returns_ok(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "version" in body


def test_post_code_returns_skill(client: TestClient, stub_coder: _StubCoder) -> None:
    res = client.post("/api/code", json={"brief": "say hi"})
    assert res.status_code == 200
    assert res.json() == {"skill_id": "demo"}
    assert stub_coder.calls[0] == ("code", "say hi")


def test_post_code_requires_brief(client: TestClient) -> None:
    res = client.post("/api/code", json={"brief": ""})
    assert res.status_code == 400


def test_post_workflow(client: TestClient) -> None:
    res = client.post("/api/workflow", json={"brief": "weather + dressing"})
    assert res.status_code == 200
    body = res.json()
    assert body["workflow_id"] == "wf-1"
    assert "graph" in body


def test_post_run_skill(client: TestClient, stub_coder: _StubCoder) -> None:
    res = client.post("/api/run/foo", json={"x": 1})
    assert res.status_code == 200
    assert stub_coder.calls[0] == ("run", ("foo", {"x": 1}))


def test_post_index(client: TestClient, stub_coder: _StubCoder, tmp_path) -> None:
    res = client.post("/api/index", json={"root": str(tmp_path)})
    assert res.status_code == 200
    assert res.json() == {"files": 3, "symbols": 12}


def test_post_edit(client: TestClient) -> None:
    res = client.post("/api/edit", json={"brief": "rename foo→bar", "root": "."})
    assert res.status_code == 200
    body = res.json()
    assert body["patch_id"] == "p-1"


def test_post_apply(client: TestClient) -> None:
    res = client.post(
        "/api/apply",
        json={
            "patch": {
                "patch_id": "p-9",
                "summary": "x",
                "rationale": "y",
                "edits": [],
            },
            "root": ".",
            "dry_run": True,
        },
    )
    assert res.status_code == 200
    assert res.json() == {"patch_id": "p-9", "applied": True}


def test_post_heal(client: TestClient) -> None:
    res = client.post(
        "/api/heal",
        json={"brief": "fix tests", "root": ".", "max_rounds": 2},
    )
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_post_publish(client: TestClient, stub_coder: _StubCoder) -> None:
    res = client.post(
        "/api/publish",
        json={
            "skill_id": "demo",
            "base_url": "https://m.example.com",
            "admin_token": "tok",
            "dry_run": True,
        },
    )
    assert res.status_code == 200
    assert res.json()["published"] is True
    skill_id, kw = stub_coder.calls[0][1]
    assert skill_id == "demo"
    assert kw["dry_run"] is True
