import zipfile
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def office_bytes(suffix):
    if suffix == "pdf":
        return b"%PDF-1.4\n1 0 obj <<>> endobj\n%%EOF\n"
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        member = "word/document.xml" if suffix == "docx" else "ppt/presentation.xml"
        content_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
            if suffix == "docx"
            else "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
        )
        archive.writestr(
            "[Content_Types].xml",
            f'<Types><Override PartName="/{member}" ContentType="{content_type}"/></Types>',
        )
        archive.writestr(
            "word/document.xml" if suffix == "docx" else "ppt/presentation.xml", "<document/>"
        )
    return stream.getvalue()


@pytest.mark.parametrize(
    "suffix, generator, reader",
    [
        ("pdf", "pdf-generate-employee", "pdf-full-read-employee"),
        ("docx", "word-generate-employee", "word-full-read-employee"),
        ("pptx", "ppt-generate-employee", "ppt-full-read-employee"),
    ],
)
@pytest.mark.parametrize("dispatch_path", ["registered", "direct"])
def test_generated_office_file_owned_handoff(
    tmp_path, monkeypatch, trusted_actor, suffix, generator, reader, dispatch_path
):
    from app.application.agent_orchestrator.artifact_files import artifact_path
    from app.application.employee_runtime import executor
    from app.application.employee_runtime.agent import EmployeeAgent
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot
    from app.domain.shared_services.tools_workflow_workspace import _registered_router_employee
    from app.infrastructure.tenant_scope import tenant_scope
    from app.mod_sdk import employee_tool_registry

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    owner, other = trusted_actor(user_id=7), trusted_actor(user_id=8)
    path = tmp_path / "outputs" / ("result." + suffix)
    path.parent.mkdir()
    content = office_bytes(suffix)
    path.write_bytes(content)
    original_execute = executor.execute_employee_task_local

    def generator_or_reader(employee_id, *args, **kwargs):
        if employee_id == generator:
            return {"success": True, "result": {"outputs": [{"output_path": str(path)}]}}
        return original_execute(employee_id, *args, **kwargs)

    monkeypatch.setattr(executor, "execute_employee_task_local", generator_or_reader)
    read_payloads = []

    def read_snapshot(self, task, payload, **kwargs):
        snapshot = Path(payload["file_path"])
        assert snapshot.suffix == "." + suffix
        assert snapshot.read_bytes() == content
        assert snapshot != path
        read_payloads.append(dict(payload))
        return {"success": True, "result": {"outputs": [{"output": "read verified snapshot"}]}}

    monkeypatch.setattr(EmployeeAgent, "run", read_snapshot)
    context = {**owner.context, "run_id": "office-run"}
    with tenant_scope(owner.tenant_id):
        if dispatch_path == "direct":
            from app.application.tools.workflow_tools.dispatch import (
                execute_registered_workflow_tool,
            )

            monkeypatch.setattr(
                employee_tool_registry, "is_employee_tool", lambda name: name == generator
            )
            monkeypatch.setattr(
                employee_tool_registry, "resolve_tool_to_pack_id", lambda name: name
            )
            exported = execute_registered_workflow_tool(
                generator, "execute", {"task": "生成文件", "_runtime_context": context}
            )
        else:
            exported = _registered_router_employee(
                "execute", {"employee_id": generator, "task": "生成文件"}, context, "normal", ""
            )
        assert exported["success"]
        receipt = exported["artifacts"][0]
        assert receipt["artifact_id"].startswith(suffix + "_")
        assert receipt["metadata"]["owner_user_id"] == str(owner.user_id)
        context["node_outputs"] = {"generated": exported}
        path.unlink()  # Only the immutable registered artifact remains available.
        for reference in [exported["data"]["file_path"], receipt["uri"]]:
            result = _registered_router_employee(
                "execute",
                {"employee_id": reader, "task": "读取生成文件", "input": {"file_path": reference}},
                context,
                "normal",
                "",
            )
            assert result["success"], result
        assert len(read_payloads) == 2
        wrong_reader = _registered_router_employee(
            "execute",
            {
                "employee_id": "csv-full-read-employee",
                "task": "错误读取器",
                "input": {"file_path": receipt["uri"]},
            },
            context,
            "normal",
            "",
        )
        assert wrong_reader["success"] is False
        assert wrong_reader["data"]["error_code"] == "employee_file_access_denied"
        assert len(read_payloads) == 2
        for wrong in [{**context, **other.context}, {**context, "run_id": "other-run"}]:
            with pytest.raises((PermissionError, FileNotFoundError)):
                with workflow_file_snapshot(exported["data"]["file_path"], wrong):
                    pytest.fail("foreign receipt must not be exposed")
        for field, value in [("mime_type", "text/plain"), ("name", "wrong.csv")]:
            tampered = deepcopy(exported)
            tampered["artifacts"][0][field] = value
            with pytest.raises(ValueError, match="format"):
                with workflow_file_snapshot(
                    exported["data"]["file_path"],
                    {**context, "node_outputs": {"generated": tampered}},
                ):
                    pytest.fail("format mismatch must not be exposed")
        artifact_path("office-run", receipt["artifact_id"]).write_bytes(b"tampered")
        with pytest.raises(ValueError, match="checksum"):
            with workflow_file_snapshot(receipt["uri"], context):
                pytest.fail("tampered bytes must not be exposed")
    with tenant_scope(999):
        with pytest.raises(PermissionError):
            with workflow_file_snapshot(receipt["uri"], context):
                pytest.fail("wrong tenant must not be exposed")


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_direct_generator_file_is_readable_and_failed_receipt_stays_failed(
    tmp_path, monkeypatch, trusted_actor, suffix
):
    from app.application.employee_runtime import executor
    from app.application.tools import workflow_spreadsheet_scope as scope
    from app.application.tools.workflow_tools.dispatch import execute_registered_workflow_tool
    from app.infrastructure.tenant_scope import tenant_scope
    from app.mod_sdk import employee_tool_registry

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    owner = trusted_actor(user_id=7)
    path = tmp_path / "outputs" / ("result." + suffix)
    path.parent.mkdir()
    context = {**owner.context, "run_id": "spreadsheet-run", "workspace_root": str(path.parent)}
    content = b"amount\n120\n80\n"
    if suffix == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        for row in [["amount"], [120], [80]]:
            workbook.active.append(row)
        workbook.save(path)
        content = path.read_bytes()
    else:
        path.write_bytes(content)
    generator = "csv-generate-employee" if suffix == "csv" else "excel-generate-employee"
    monkeypatch.setattr(employee_tool_registry, "is_employee_tool", lambda name: name == generator)
    monkeypatch.setattr(employee_tool_registry, "resolve_tool_to_pack_id", lambda name: name)
    calls = []

    def generate(*args, **kwargs):
        calls.append(args)
        return {"success": True, "result": {"outputs": [{"output_path": str(path)}]}}

    monkeypatch.setattr(executor, "execute_employee_task_local", generate)
    with tenant_scope(owner.tenant_id):
        result = execute_registered_workflow_tool(
            generator, "execute", {"_runtime_context": context}
        )
        assert result["success"] and result["artifact_postcondition"]["verified"]
        context["node_outputs"] = {"generate": result}
        path.unlink()
        with scope.workflow_file_snapshot(result["data"]["file_path"], context) as snapshot:
            assert snapshot.read_bytes() == content
        path.write_bytes(content)

        def fail_receipt(*args, **kwargs):
            raise OSError("artifact storage unavailable")

        monkeypatch.setattr(scope, "store_employee_output", fail_receipt)
        failed = execute_registered_workflow_tool(
            generator, "execute", {"_runtime_context": context}
        )
        assert not failed["success"] and not failed.get("artifacts")
        assert len(calls) == 2  # Receipt failure must not invoke the worker again.


@pytest.mark.parametrize(
    "name, content",
    [
        ("fake.pdf", b"not pdf"),
        ("fake.docx", office_bytes("pptx")),
        ("fake.pptx", b"not zip"),
        ("fake.exe", b"payload"),
    ],
)
def test_reject_mislabeled_office_content(tmp_path, monkeypatch, name, content):
    from app.application.agent_orchestrator.artifact_files import store_run_file

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        store_run_file("office-run", content, name=name, owner_user_id=7, tenant_id="7")
    assert not (tmp_path / "agent-artifacts").exists()


@pytest.mark.parametrize(
    "manifest", [b"not XML", b"<Types/>", b'<!DOCTYPE x [<!ENTITY a "boom">]><Types>&a;</Types>']
)
def test_reject_invalid_ooxml_content_types(tmp_path, monkeypatch, manifest):
    from app.application.agent_orchestrator.artifact_files import store_run_file

    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", manifest)
        archive.writestr("word/document.xml", "<document/>")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        store_run_file(
            "office-run", stream.getvalue(), name="bad.docx", owner_user_id=7, tenant_id="7"
        )
    assert not (tmp_path / "agent-artifacts").exists()


@pytest.mark.parametrize("owner, tenant", [(None, "7"), (True, "7"), (7, "")])
def test_office_registration_requires_explicit_identity(tmp_path, monkeypatch, owner, tenant):
    from app.application.agent_orchestrator.artifact_files import store_run_file

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="scope"):
        store_run_file(
            "office-run",
            office_bytes("pdf"),
            name="valid.pdf",
            owner_user_id=owner,
            tenant_id=tenant,
        )
    assert not (tmp_path / "agent-artifacts").exists()


@pytest.mark.parametrize("suffix", ["xls", "xlsm"])
def test_legacy_spreadsheet_suffix_is_preserved(tmp_path, monkeypatch, suffix):
    from app.application.agent_orchestrator.artifact_files import (
        artifact_path,
        read_verified_spreadsheet,
        store_spreadsheet,
    )

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    receipt = store_spreadsheet("table-run", b"legacy bytes", name="source." + suffix)
    assert artifact_path("table-run", receipt["artifact_id"]).suffix == "." + suffix
    assert read_verified_spreadsheet("table-run", receipt) == b"legacy bytes"
