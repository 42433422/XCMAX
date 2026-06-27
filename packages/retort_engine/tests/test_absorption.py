from __future__ import annotations

from pathlib import Path

from retort_engine.absorption import run_absorption
from retort_engine.models import ExternalProjectRef
from retort_engine.sources import parse_github_url, resolve_external_project
from tests.test_evidence_evaluator import create_focused_tool_package, create_incomplete_package


def test_parse_github_url_owner_repo_and_tree_ref() -> None:
    repo = parse_github_url("https://github.com/openai/codex/tree/main")
    assert repo.owner == "openai"
    assert repo.repo == "codex"
    assert repo.ref == "main"


def test_resolve_external_project_from_local_path(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    ref = resolve_external_project(external_path=str(external))
    assert ref.source_type == "local_path"


def test_absorption_generates_tasks_from_stronger_external_project(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    create_incomplete_package(own)
    create_focused_tool_package(external)
    result = run_absorption(own_project=str(own), external_path=str(external), max_tasks=6)
    assert result.status == "tasks_generated"
    assert result.tasks
    assert result.semantic_findings


def test_absorption_uses_real_github_url_case_without_network(tmp_path: Path, monkeypatch) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    create_incomplete_package(own)
    create_focused_tool_package(external)

    def fake_resolve_external_project(**kwargs) -> ExternalProjectRef:
        assert kwargs["github_url"] == "https://github.com/openai/codex"
        return ExternalProjectRef(kwargs["github_url"], "github", str(external), "main")

    monkeypatch.setattr("retort_engine.absorption.resolve_external_project", fake_resolve_external_project)
    result = run_absorption(own_project=str(own), github_url="https://github.com/openai/codex", max_tasks=2)
    assert result.external_ref.source_type == "github"
    assert result.tasks


def test_absorption_writes_employee_queue_and_history(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    queue_path = tmp_path / "employee_queue.jsonl"
    history_path = tmp_path / "retort_history.sqlite"
    create_incomplete_package(own)
    create_focused_tool_package(external)
    result = run_absorption(own_project=str(own), external_path=str(external), max_tasks=3, employee_queue_path=str(queue_path), history_store=str(history_path))
    assert result.tasks
    assert queue_path.is_file()
    assert history_path.is_file()
