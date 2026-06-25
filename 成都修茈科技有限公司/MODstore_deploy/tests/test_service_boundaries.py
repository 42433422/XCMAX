"""Static service-boundary lint for Employee / Workflow / LLM domains.

The Python monolith currently contains a known set of cross-domain imports.
Each entry in ``LEGACY_CROSS_DOMAIN_IMPORTS`` is a piece of technical debt
that must be removed before the corresponding service is extracted (see
``docs/SERVICE_BOUNDARIES.md`` §3). This test:

- Fails when a *new* cross-domain import is introduced anywhere in
  ``modstore_server`` outside the legacy snapshot.
- Fails when one of the snapshot entries is finally removed but the snapshot
  is not updated, so the budget keeps shrinking instead of silently
  forgetting that the debt is gone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "modstore_server"


def _domain_for(module: str) -> str | None:
    """Return the domain prefix for a module file or imported module path."""

    name = module.replace("\\", "/")
    if name.startswith(("modstore_server.",)):
        name = name[len("modstore_server.") :]
    name = name.replace(".", "/")

    if name.startswith("services/"):
        # services/ ports ARE the cross-domain bridge; lint exempts them on
        # both sides (importer and importee).
        return "services"
    if (
        name.startswith("api/")
        or name.startswith("application/")
        or name.startswith("infrastructure/")
    ):
        # The application/ layer can call across domains because it is the
        # composition root. We still track explicit illegal imports below.
        return None
    if name.startswith(
        (
            "employee_runtime",
            "employee_executor",
            "employee_config_v2",
            "employee_api",
            "employee_pack_export",
            "employee_ai_scaffold",
            "workflow_employee_scaffold",
        )
    ):
        return "employee"
    if name.startswith(
        (
            "workflow_api",
            "workflow_engine",
            "workflow_scheduler",
            "workflow_variables",
            "workflow_nl_graph",
            "workflow_mod_link",
        )
    ):
        return "workflow"
    if name.startswith(
        (
            "llm_api",
            "llm_chat_proxy",
            "llm_key_resolver",
            "llm_catalog",
            "llm_billing",
            "llm_crypto",
        )
    ):
        return "llm"
    if name.startswith("llm_model_taxonomy"):
        # Pure data/constants module; treated as platform-shared.
        return None
    if name.startswith(
        ("knowledge_vector_api", "knowledge_vector_store", "knowledge_ingest", "embedding_service")
    ):
        return "llm"
    return None


LEGACY_CROSS_DOMAIN_IMPORTS: frozenset[tuple[str, str, str]] = frozenset(
    {
        # workflow_api/execution.py directly imports llm_billing — legacy coupling pre-dates
        # service boundary enforcement; track as debt, do not add new entries
        ("workflow_api/execution.py", "workflow", "modstore_server.llm_billing"),
    }
)
"""Frozen technical debt budget. Removing an entry from this set is the only
permitted change; CI fails if the actual offender list grows or shrinks
without an update here."""


_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(modstore_server\.[\w\.]+)\s+import\s+|import\s+(modstore_server\.[\w\.]+))",
    re.MULTILINE,
)


def _scan_offenders() -> set[tuple[str, str, str]]:
    offenders: set[tuple[str, str, str]] = set()
    for path in ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            rel = path.relative_to(ROOT).as_posix()
        except ValueError:
            continue
        importer_domain = _domain_for(rel)
        if importer_domain is None or importer_domain == "services":
            continue
        text = path.read_text(encoding="utf-8")
        for match in _IMPORT_RE.finditer(text):
            imported = match.group(1) or match.group(2)
            if not imported:
                continue
            target_domain = _domain_for(imported)
            if target_domain is None or target_domain == "services":
                continue
            if target_domain == importer_domain:
                continue
            offenders.add((rel, importer_domain, imported))
    return offenders


def test_service_boundary_budget_matches_snapshot():
    actual = _scan_offenders()

    new_violations = sorted(actual - LEGACY_CROSS_DOMAIN_IMPORTS)
    if new_violations:
        formatted = "\n".join(f"  {entry}" for entry in new_violations)
        pytest.fail(
            "New cross-domain imports detected. Either route the call through a "
            "client port in modstore_server/services/* or, if absolutely "
            "unavoidable, add an explicit entry to "
            "LEGACY_CROSS_DOMAIN_IMPORTS in this test.\n" + formatted
        )

    removed = sorted(LEGACY_CROSS_DOMAIN_IMPORTS - actual)
    if removed:
        formatted = "\n".join(f"  {entry}" for entry in removed)
        pytest.fail(
            "Service boundary tech debt has SHRUNK; remove the now-unused "
            "entries from LEGACY_CROSS_DOMAIN_IMPORTS in this test so the "
            "budget keeps ratcheting downward.\n" + formatted
        )


def test_service_ports_module_exists_and_exposes_clients():
    from modstore_server.services import (
        CatalogClient,
        EmployeeRuntimeClient,
        InProcessCatalogClient,
        InProcessEmployeeRuntimeClient,
        InProcessLlmChatClient,
        InProcessWorkflowEngineClient,
        LlmChatClient,
        WorkflowEngineClient,
        get_default_catalog_client,
        get_default_employee_client,
        get_default_llm_client,
        get_default_workflow_client,
        set_default_catalog_client,
        set_default_employee_client,
        set_default_llm_client,
        set_default_workflow_client,
    )

    assert isinstance(get_default_catalog_client(), CatalogClient)
    assert isinstance(get_default_employee_client(), EmployeeRuntimeClient)
    assert isinstance(get_default_llm_client(), LlmChatClient)
    assert isinstance(get_default_workflow_client(), WorkflowEngineClient)

    assert isinstance(InProcessCatalogClient(), CatalogClient)
    assert isinstance(InProcessEmployeeRuntimeClient(), EmployeeRuntimeClient)
    assert isinstance(InProcessLlmChatClient(), LlmChatClient)
    assert isinstance(InProcessWorkflowEngineClient(), WorkflowEngineClient)

    set_default_catalog_client(None)
    set_default_employee_client(None)
    set_default_llm_client(None)
    set_default_workflow_client(None)
    # Re-fetching reconstructs default in-process implementations.
    assert isinstance(get_default_catalog_client(), InProcessCatalogClient)
    assert isinstance(get_default_employee_client(), InProcessEmployeeRuntimeClient)
    assert isinstance(get_default_llm_client(), InProcessLlmChatClient)
    assert isinstance(get_default_workflow_client(), InProcessWorkflowEngineClient)


def test_employee_client_can_be_overridden():
    from modstore_server.services import (
        EmployeeRuntimeClient,
        get_default_employee_client,
        set_default_employee_client,
    )

    class _Stub(EmployeeRuntimeClient):
        def list_employees(self):
            return [{"id": "stub"}]

        def get_employee_status(self, employee_id):
            return {"employee_id": employee_id, "status": "stub"}

        def execute_task(self, *, employee_id, task, input_data=None, user_id=None):
            return {"employee_id": employee_id, "task": task, "user_id": user_id}

    stub = _Stub()
    set_default_employee_client(stub)
    try:
        assert get_default_employee_client() is stub
        assert stub.list_employees() == [{"id": "stub"}]
        assert stub.execute_task(employee_id="x", task="y", user_id=1)["task"] == "y"
    finally:
        set_default_employee_client(None)


def test_llm_request_response_round_trip():
    from modstore_server.services import LlmChatRequest, LlmChatResponse

    request = LlmChatRequest(
        provider="openai",
        model="gpt-x",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-test",
    )
    assert request.provider == "openai"
    assert request.messages[0]["content"] == "hi"

    response = LlmChatResponse.from_dict(
        {"ok": True, "content": "hello", "usage": {"prompt_tokens": 1}}
    )
    assert response.ok is True
    assert response.content == "hello"
    assert response.usage["prompt_tokens"] == 1


def test_workflow_client_calls_underlying_engine(monkeypatch):
    from modstore_server.services import InProcessWorkflowEngineClient

    captured = {}

    def fake_execute(workflow_id, input_data, *, user_id=0):
        captured["call"] = (workflow_id, input_data, user_id)
        return {"ok": True}

    import modstore_server.workflow_engine as engine

    monkeypatch.setattr(engine, "execute_workflow", fake_execute)

    client = InProcessWorkflowEngineClient()
    result = client.execute_workflow(workflow_id=1, input_data={"x": 1}, user_id=7)
    assert result == {"ok": True}
    assert captured["call"] == (1, {"x": 1}, 7)
