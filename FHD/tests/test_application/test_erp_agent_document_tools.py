"""ERP Agent document-worker integration: real function calls, never text protocol."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.capability_catalog import available_employees
from app.application.tools.registered_capabilities import ERP_CAPABILITY_TOOL_NAME
from app.application.tools.workflow import (
    get_workflow_tool_registry,
    invalidate_workflow_tool_registry,
)
from app.infrastructure.tenant_scope import tenant_scope
from app.mod_sdk.employee_pack_compat import list_office_pack_catalog
from app.mod_sdk.employee_tool_registry import (
    build_employee_tools_status,
    invalidate_employee_tool_cache,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def document_calls(tmp_path, monkeypatch, trusted_actor):
    """Carry the original actor and persisted calls across real document workers."""
    from app.application.agent_orchestrator.artifact_files import read_verified_run_file
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.mod_sdk.employee_tool_registry import execute_employee_tool

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    owner = trusted_actor(role="admin")
    repository = SQLAlchemyAgentRunRepository(session_factory=owner.factory)
    run = AgentRun(
        str(owner.user_id),
        "生成文档并由独立读取员工回读",
        status="running",
        metadata={"runtime_context": owner.context},
    )
    with tenant_scope(owner.tenant_id):
        repository.save(run)

    def execute(name, payload, node_id):
        params = {"employee_id": name, "input": payload}
        step = AgentStep(node_id=node_id, tool_id="employee", action="execute", params=params)
        call = ToolCall(
            step_id=step.step_id,
            node_id=node_id,
            tool_id="employee",
            action="execute",
            params=params,
        )
        with tenant_scope(owner.tenant_id):
            stored = repository.get(run.run_id)
            assert stored is not None
            stored.steps.append(step)
            stored.tool_calls.append(call)
            repository.save(stored)
            stored = repository.get(run.run_id)
            assert stored is not None
            original_call = stored.tool_calls[-1]
            context = {
                **stored.metadata["runtime_context"],
                "run_id": stored.run_id,
                "step_id": original_call.step_id,
                "node_id": original_call.node_id,
                "call_id": original_call.call_id,
                "input_sha256": canonical_hash(original_call.params),
                "node_outputs": {
                    prior.node_id: prior.output
                    for prior in stored.steps
                    if prior.status == "completed"
                },
            }
            assert context["_actor_authorization"] == owner.context["_actor_authorization"]
            result = json.loads(
                execute_employee_tool(
                    name, payload, str(tmp_path), user_id=owner.user_id, runtime_context=context
                )
            )
            stored.steps[-1].output = original_call.output = result
            stored.steps[-1].status = original_call.status = (
                "completed" if result["success"] else "failed"
            )
            repository.save(stored)
            assert result["success"] is True, result
            assert result["artifact_postcondition"]["verified"] is True
            assert result["artifacts"]
            contents = {}
            expected_metadata = {
                "run_id": stored.run_id,
                "owner_user_id": str(owner.user_id),
                "tenant_id": str(owner.tenant_id),
                "step_id": original_call.step_id,
                "node_id": original_call.node_id,
                "call_id": original_call.call_id,
                "params_sha256": canonical_hash(original_call.params),
            }
            for receipt in result["artifacts"]:
                assert receipt["uri"] == (
                    f"/api/agent/runs/{stored.run_id}/artifacts/{receipt['artifact_id']}"
                )
                assert {
                    key: receipt["metadata"][key] for key in expected_metadata
                } == expected_metadata
                contents[receipt["uri"]] = read_verified_run_file(stored.run_id, receipt)
            return SimpleNamespace(result=result, contents=contents)

    return execute


def test_all_ten_built_in_document_workers_are_registered_and_runnable(trusted_actor) -> None:
    expected = set(list_office_pack_catalog()["pack_ids"])
    assert len(expected) == 10
    invalidate_employee_tool_cache()
    invalidate_workflow_tool_registry()
    status = build_employee_tools_status()
    actor = trusted_actor(permissions=["employee.list", "employee.execute"])
    assert get_workflow_tool_registry() == []
    (model_tool,) = get_workflow_tool_registry(actor.context)
    function = model_tool["function"]
    assert function["name"] == ERP_CAPABILITY_TOOL_NAME
    assert {
        branch["properties"]["action"]["enum"][0]
        for branch in function["parameters"]["anyOf"]
        if branch["properties"]["tool_id"]["enum"] == ["employee"]
    } >= {"list", "execute"}
    discovered = {row["employee_id"] for row in available_employees(actor.context)}

    assert status["office_ready"] is True
    assert status["missing_office_pack_ids"] == []
    # Some non-document host packs may intentionally be unavailable in a
    # lightweight test environment.  The release contract here is that each
    # bundled office employee is executable, not that every optional pack is.
    assert not (expected & set(status["runtime_missing_pack_ids"]))
    assert expected <= set(status["registered_tool_names"])
    assert expected <= discovered


def test_employee_tool_lookup_self_heals_after_scoped_discovery_cache(monkeypatch) -> None:
    """A temporary one-pack discovery must not poison later desktop lookups."""
    from app.mod_sdk import employee_tool_registry as registry

    installed = registry.list_installed_pack_records()
    narrow = [row for row in installed if row.get("pack_id") == "csv-full-read-employee"]
    assert len(narrow) == 1

    registry.invalidate_employee_tool_cache()
    with monkeypatch.context() as scoped:
        scoped.setattr(registry, "list_installed_pack_records", lambda: narrow)
        assert (
            registry.resolve_tool_to_pack_id("csv-full-read-employee") == "csv-full-read-employee"
        )

    assert registry.resolve_tool_to_pack_id("excel-generate-employee") == "excel-generate-employee"


def test_word_generator_writes_an_actual_document_from_a_chat_request(
    tmp_path, monkeypatch, document_calls
) -> None:
    """A forced chat call must yield a file, even when no JSON was uploaded."""
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    def unexpected_cognition(*_args, **_kwargs):
        raise AssertionError("bundled Office conversion must not need an LLM")

    monkeypatch.setattr(
        "app.application.employee_runtime.agent._ex._cognition_fhd",
        unexpected_cognition,
    )

    request = "起草一份验收用销售合同，包含交付与付款条款。"
    generation = document_calls("word-generate-employee", {"user_request": request}, "generate")
    result = generation.result

    assert result["success"] is True
    assert result["artifact_postcondition"]["verified"] is True
    assert Path(result["artifact_postcondition"]["paths"][0]).suffix == ".docx"
    generated = list((tmp_path / "outputs").glob("*.docx"))
    assert generated and generated[0].stat().st_size > 0
    [receipt] = result["artifacts"]
    assert generation.contents[receipt["uri"]] == generated[0].read_bytes()
    reading = document_calls("word-full-read-employee", {"file_path": receipt["uri"]}, "read")
    parsed = json.loads(reading.contents[reading.result["data"]["file_path"]])
    assert request in parsed["plain_text"]


@pytest.mark.parametrize(
    ("tool_name", "reader_name", "suffix"),
    [
        ("excel-generate-employee", "excel-full-read-employee", ".xlsx"),
        ("csv-generate-employee", "csv-full-read-employee", ".csv"),
        ("pdf-generate-employee", "pdf-full-read-employee", ".pdf"),
        ("ppt-generate-employee", "ppt-full-read-employee", ".pptx"),
    ],
)
def test_other_document_generators_write_files_without_modstore_source(
    tmp_path, monkeypatch, document_calls, tool_name: str, reader_name: str, suffix: str
) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    request = "生成一份验收用业务摘要，包含客户、金额和交付状态。"
    generation = document_calls(tool_name, {"user_request": request}, "generate")
    result = generation.result

    assert result["success"] is True
    assert result["artifact_postcondition"]["verified"] is True
    assert Path(result["artifact_postcondition"]["paths"][0]).suffix == suffix
    generated = list((tmp_path / "outputs").glob(f"*{suffix}"))
    assert generated and generated[0].stat().st_size > 0
    [receipt] = result["artifacts"]
    assert generation.contents[receipt["uri"]] == generated[0].read_bytes()
    reading = document_calls(reader_name, {"file_path": receipt["uri"]}, "read")
    parsed = json.loads(reading.contents[reading.result["data"]["file_path"]])
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        document = parsed["document"]
        assert document["source_ref"]["source_sha256"] == receipt["metadata"]["sha256"]
        assert [
            (cell["address"], cell["value"], cell["value_type"], cell["value_state"])
            for cell in document["sheets"][0]["cells"]
        ] == [("A1", "内容", "text", "present"), ("A2", request, "text", "present")]
        workbook = load_workbook(generated[0], read_only=True)
        try:
            assert workbook["Sheet1"]["A1"].value == "内容"
            assert workbook["Sheet1"]["A2"].value == request
        finally:
            workbook.close()
    elif suffix == ".csv":
        assert parsed["rows"] == [{"内容": request}]
    elif suffix == ".pdf":
        assert parsed["plain_text"] == request
    else:
        assert parsed["slides"][0]["title"] == request
