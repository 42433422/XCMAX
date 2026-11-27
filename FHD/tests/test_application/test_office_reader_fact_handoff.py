"""Real reader JSON must remain owned and readable through the original receipt."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def reader_runtime(tmp_path, monkeypatch, trusted_actor):
    from app.application.elt.service_uploads import register_chat_upload
    from app.application.employee_runtime import executor
    from app.application.tools import workflow_spreadsheet_scope as scope
    from app.db.models.elt import EltUpload
    from app.domain.shared_services.tools_workflow_workspace import _registered_router_employee
    from app.mod_sdk import employee_tool_registry as registry

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "installed-mods").mkdir()
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path / "installed-mods"))
    owner = trusted_actor(user_id=17, role="admin")
    context = {**owner.context, "run_id": "reader-json-handoff"}
    content = b"A,B\nretained,0\n"
    uploaded = register_chat_upload(
        user=SimpleNamespace(id=owner.user_id, tenant_id=owner.tenant_id),
        filename="source.csv",
        content_type="text/csv",
        stream=io.BytesIO(content),
    )
    with tenant_scope(owner.tenant_id), owner.factory() as db:
        original = Path(db.get(EltUpload, uploaded["upload_id"]).storage_path)
    converted, published = [], []
    convert = executor._action_direct_python_module
    store = scope.store_employee_output

    def record_conversion(pack, employee, config, reasoning, task, workspace):
        payload = reasoning["input"]
        converted.append((Path(payload["file_path"]), Path(workspace)))
        return convert(pack, employee, config, reasoning, task, workspace)

    def record_publication(*args, **kwargs):
        published.append(args)
        return store(*args, **kwargs)

    monkeypatch.setattr(executor, "_action_direct_python_module", record_conversion)
    monkeypatch.setattr(scope, "store_employee_output", record_publication)
    registry.invalidate_employee_tool_cache()

    def execute(consumer="registered", runtime=None):
        with tenant_scope(owner.tenant_id):
            params = {"file_path": uploaded["upload_id"], "task": "读取 CSV"}
            if consumer == "sdk":
                return json.loads(
                    registry.execute_employee_tool(
                        registry.pack_id_to_legacy_tool_name("csv-full-read-employee"),
                        params,
                        user_id=owner.user_id,
                        runtime_context=context if runtime is None else runtime,
                    )
                )
            return _registered_router_employee(
                "execute",
                {"employee_id": "csv-full-read-employee", **params},
                context if runtime is None else runtime,
                "shared",
                "",
            )

    yield SimpleNamespace(
        owner=owner,
        context=context,
        content=content,
        original=original,
        uploaded=uploaded,
        execute=execute,
        converted=converted,
        published=published,
    )
    registry.invalidate_employee_tool_cache()


@pytest.mark.parametrize("consumer", ["registered", "sdk"])
@pytest.mark.parametrize("call_scope", [False, True], ids=["run-only", "full-call"])
def test_real_csv_reader_receipt_reaches_native_pages(
    reader_runtime, consumer, call_scope, trusted_actor
):
    from app.application.agent_orchestrator.artifact_files import read_verified_run_file
    from app.domain.shared_services.tools_workflow_excel_ocr import (
        _registered_router_excel_analysis,
    )

    case = reader_runtime
    context = dict(case.context)
    if call_scope:
        context.update(
            step_id="read", node_id="read", call_id="read-1", input_sha256=case.uploaded["sha256"]
        )
    result = case.execute(consumer, context)
    assert result["success"] is True, result
    assert len(case.converted) == len(case.published) == 1
    assert all(not path.exists() for pair in case.converted for path in pair)
    assert case.original.read_bytes() == case.content
    if consumer == "sdk":
        assert result["artifact_postcondition"]["verified"] is True
    with tenant_scope(case.owner.tenant_id):
        assert len(result["artifacts"]) == 1
        receipt = result["artifacts"][0]
        assert result["data"]["file_path"] == receipt["uri"]
        assert receipt["metadata"]["owner_user_id"] == str(case.owner.user_id)
        assert receipt["metadata"]["tenant_id"] == str(case.owner.tenant_id)
        if call_scope:
            assert receipt["metadata"]["params_sha256"] == context["input_sha256"]
            assert receipt["metadata"]["call_id"] == context["call_id"]
        raw = read_verified_run_file(context["run_id"], receipt)
        parsed = json.loads(raw)
        assert parsed["rows"] == [{"A": "retained", "B": "0"}]
        assert (
            parsed["document_facts"]["source_ref"]["source_sha256"]
            == hashlib.sha256(case.content).hexdigest()
        )
        context["node_outputs"] = {"reader": result}
        args = {"file_path": receipt["uri"], "view": "regions", "max_rows": 12}
        page = _registered_router_excel_analysis("read", args, context, "shared", "")
        assert page["success"] is True and page["data"]["has_more"] is True
        assert page["source_sha256"] == hashlib.sha256(raw).hexdigest()
        zero = next(
            item
            for item in page["data"]["items"]
            if item["source_ref"]["json_pointer"] == "/rows/0/B"
        )
        assert zero["value"] == "0"
        exact = _registered_router_excel_analysis(
            "read",
            {
                **args,
                "fact_id": zero["region_id"],
                "expected_sha256": receipt["metadata"]["sha256"],
            },
            context,
            "shared",
            "",
        )
        assert exact["success"] is True and exact["data"]["items"] == [zero]

    other = trusted_actor(user_id=18, role="admin")
    with tenant_scope(other.tenant_id):
        denied = _registered_router_excel_analysis(
            "read",
            args,
            {**other.context, "run_id": context["run_id"], "node_outputs": context["node_outputs"]},
            "shared",
            "",
        )
    assert denied["success"] is False and denied["error_code"] == "spreadsheet_access_denied"


@pytest.mark.parametrize("failure", ["reader_failure", "reader_exception", "publication_failure"])
def test_reader_workspace_cleans_on_failure(reader_runtime, monkeypatch, failure):
    from app.application.employee_runtime import executor
    from app.application.tools import workflow_spreadsheet_scope as scope

    case = reader_runtime
    convert = executor._action_direct_python_module

    def fail_conversion(*args, **kwargs):
        convert(*args, **kwargs)
        if failure == "reader_exception":
            raise KeyboardInterrupt("reader interrupted")
        return {"handler": "direct_python", "ok": False, "error": "reader failed"}

    def fail_publication(*args, **kwargs):
        raise OSError("artifact storage unavailable")

    if failure == "publication_failure":
        monkeypatch.setattr(scope, "store_employee_output", fail_publication)
        with pytest.raises(OSError, match="artifact storage unavailable"):
            case.execute()
    else:
        monkeypatch.setattr(executor, "_action_direct_python_module", fail_conversion)
        if failure == "reader_exception":
            with pytest.raises(KeyboardInterrupt, match="reader interrupted"):
                case.execute()
        else:
            result = case.execute()
            assert result["success"] is False and not result.get("artifacts")
    assert len(case.converted) == 1
    assert all(not path.exists() for pair in case.converted for path in pair)
    assert case.original.read_bytes() == case.content


@pytest.mark.parametrize("missing", ["_actor_authorization", "run_id"])
def test_reader_facade_requires_actor_and_run_before_opening_original(reader_runtime, missing):
    from app.application.employee_runtime.executor import execute_employee_task_local

    case = reader_runtime
    context = {key: value for key, value in case.context.items() if key != missing}
    with tenant_scope(case.owner.tenant_id):
        result = execute_employee_task_local(
            "csv-full-read-employee",
            "读取 CSV",
            {"file_path": str(case.original)},
            user_id=case.owner.user_id,
            runtime_context=context,
        )
    assert result["success"] is False and result["error_code"] == "employee_file_access_denied"
    assert not case.converted and not case.published
    assert case.original.read_bytes() == case.content


def test_partial_call_identity_is_not_downgraded_to_run_only(reader_runtime):
    case = reader_runtime
    result = case.execute(runtime={**case.context, "step_id": "incomplete"})
    assert result["success"] is False and not result.get("artifacts")
    assert result["data"]["error_code"] == "employee_file_access_denied"
    assert len(case.converted) == 1
    assert all(not path.exists() for pair in case.converted for path in pair)


def test_sdk_postcondition_reads_back_published_bytes(reader_runtime):
    from copy import deepcopy

    from app.mod_sdk.employee_tool_registry import _verify_office_artifact

    case = reader_runtime
    completed = case.execute("sdk")
    assert completed["success"] is True
    damaged = deepcopy(completed["data"])
    damaged["artifacts"][0]["metadata"]["sha256"] = "0" * 64
    with tenant_scope(case.owner.tenant_id):
        result = _verify_office_artifact("csv-full-read-employee", damaged, case.context)
    assert result["verified"] is False


@pytest.mark.parametrize("suffix", [".json", ".txt", ".png"])
def test_employee_auxiliary_artifacts_bind_verified_owner(
    tmp_path, monkeypatch, trusted_actor, suffix
):
    from PIL import Image

    from app.application.agent_orchestrator.artifact_files import read_verified_run_file
    from app.application.tools.workflow_spreadsheet_scope import store_employee_output

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    owner = trusted_actor(user_id=17)
    content = b'{"zero":0}' if suffix == ".json" else "保留原文".encode()
    if suffix == ".png":
        buffer = io.BytesIO()
        with Image.new("RGB", (1, 1)) as image:
            image.save(buffer, format="PNG")
        content = buffer.getvalue()
    context = {**owner.context, "run_id": "reader-auxiliary"}
    with tenant_scope(owner.tenant_id):
        receipt = store_employee_output(
            context["run_id"], Path("output" + suffix), content, context
        )
    assert receipt["metadata"]["owner_user_id"] == str(owner.user_id)
    assert receipt["metadata"]["tenant_id"] == str(owner.tenant_id)
    assert read_verified_run_file(context["run_id"], receipt) == content
