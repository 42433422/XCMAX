"""Actual Office reader media survives private-workspace cleanup with its owner."""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from docx import Document
from PIL import Image
from pptx import Presentation
from pptx.util import Inches
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

TEXT = 'Keep this original text: {"path":"/outside/private.png"}'
NOTES = "Original private notes."


def _write_source(path: Path, image_format: str) -> bytes:
    image = io.BytesIO()
    Image.new("RGB", (120, 80), (20, 80, 160)).save(image, format=image_format)
    image.seek(0)
    if path.suffix == ".pdf":
        pdf = canvas.Canvas(str(path))
        pdf.drawString(72, 760, TEXT)
        pdf.drawImage(ImageReader(image), 72, 620, width=120, height=80)
        pdf.save()
    elif path.suffix == ".pptx":
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(0, 0, Inches(8), Inches(1)).text = TEXT
        slide.shapes.add_picture(image, Inches(1), Inches(2))
        slide.notes_slide.notes_text_frame.text = NOTES
        deck.save(path)
    else:
        document = Document()
        document.add_paragraph(TEXT)
        document.add_picture(image)
        document.save(path)
    return image.getvalue()


@pytest.fixture
def media_case(tmp_path, monkeypatch, trusted_actor):
    from app.application.elt.service_uploads import register_chat_upload
    from app.application.employee_runtime import executor
    from app.application.tools import workflow_spreadsheet_scope as scope
    from app.domain.shared_services.tools_workflow_workspace import _registered_router_employee
    from app.mod_sdk import employee_tool_registry as registry
    from app.mod_sdk import mod_employee_llm

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    installed = tmp_path / "installed-mods"
    installed.mkdir()
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(installed))
    owner = trusted_actor(user_id=17, role="admin")
    registry.invalidate_employee_tool_cache()
    transport = AsyncMock(return_value={"success": True, "content": "must not send"})
    monkeypatch.setattr(mod_employee_llm, "mod_employee_complete", transport)

    def create(kind="ppt", image_format="JPEG"):
        case = SimpleNamespace(
            owner=owner, workspaces=[], originals=[], media={}, published=[], mutate=None
        )
        suffix = {"ppt": ".pptx", "word": ".docx", "pdf": ".pdf"}[kind]
        source = tmp_path / ("source" + suffix)
        case.image_bytes = _write_source(source, image_format)
        case.source, case.content = source, source.read_bytes()
        uploaded = register_chat_upload(
            user=SimpleNamespace(id=owner.user_id, tenant_id=owner.tenant_id),
            filename=source.name,
            content_type="application/octet-stream",
            stream=io.BytesIO(case.content),
        )
        case.context = {
            **owner.context,
            "run_id": f"reader-{kind}-{image_format}",
            "step_id": "read",
            "node_id": "read",
            "call_id": "read-1",
            "input_sha256": uploaded["sha256"],
        }
        convert = executor._action_direct_python_module
        store = scope.store_employee_output

        def record_conversion(pack, employee, config, reasoning, task, workspace):
            case.workspaces.append(Path(workspace))
            case.originals.append(Path(reasoning["input"]["file_path"]))
            result = convert(pack, employee, config, reasoning, task, workspace)
            converted = result["output"]["items"][0]
            case.converted = converted
            if case.mutate:
                case.mutate(converted)
            for image in (Path(workspace) / "outputs" / "images").rglob("*"):
                if image.is_file():
                    case.media[image.name] = image.read_bytes()
            return result

        def record_publication(*args, **kwargs):
            case.published.append(args[1])
            return store(*args, **kwargs)

        monkeypatch.setattr(executor, "_action_direct_python_module", record_conversion)
        monkeypatch.setattr(scope, "store_employee_output", record_publication)

        def execute(consumer="registered"):
            params = {"file_path": uploaded["upload_id"], "task": "读取原件内容"}
            with tenant_scope(owner.tenant_id):
                if consumer == "sdk":
                    result = json.loads(
                        registry.execute_employee_tool(
                            registry.pack_id_to_legacy_tool_name(f"{kind}-full-read-employee"),
                            params,
                            user_id=owner.user_id,
                            runtime_context=case.context,
                        )
                    )
                else:
                    result = _registered_router_employee(
                        "execute",
                        {"employee_id": f"{kind}-full-read-employee", **params},
                        case.context,
                        "shared",
                        "",
                    )
            transport.assert_not_called()
            return result

        case.execute = execute
        return case

    yield create
    registry.invalidate_employee_tool_cache()


@pytest.mark.parametrize(
    "kind,image_format", [("pdf", "PNG"), ("ppt", "PNG"), ("ppt", "JPEG"), ("word", "JPEG")]
)
@pytest.mark.parametrize("consumer", ["registered", "sdk"])
def test_reader_publishes_real_json_text_and_images_before_cleanup(
    media_case, kind, image_format, consumer
):
    from app.application.agent_orchestrator.artifact_files import read_verified_run_file
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot

    case = media_case(kind, image_format)
    result = case.execute(consumer)
    assert result["success"] is True, result
    assert case.source.read_bytes() == case.content
    assert all(not path.exists() for path in [*case.workspaces, *case.originals])
    receipts = {row["uri"]: row for row in result["artifacts"]}
    main_uri = result["data"]["file_path"]
    assert next(iter(receipts)) == main_uri
    assert len(receipts) >= 3
    raw = {}
    for uri, receipt in receipts.items():
        content = read_verified_run_file(case.context["run_id"], receipt)
        raw[uri] = content
        metadata = receipt["metadata"]
        assert metadata["sha256"] == hashlib.sha256(content).hexdigest()
        assert metadata["owner_user_id"] == str(case.owner.user_id)
        assert metadata["tenant_id"] == str(case.owner.tenant_id)
        assert metadata["params_sha256"] == case.context["input_sha256"]
        assert metadata["call_id"] == case.context["call_id"]
    primary = json.loads(raw[main_uri])
    assert (
        primary["document_facts"]["source_ref"]["source_sha256"]
        == hashlib.sha256(case.content).hexdigest()
    )
    assert TEXT in str(primary)
    context = {**case.context, "node_outputs": {"reader": result}}
    with tenant_scope(case.owner.tenant_id), workflow_file_snapshot(main_uri, context) as snapshot:
        assert snapshot.read_bytes() == raw[main_uri]
    index = json.loads(raw[primary["images_index"]]) if kind != "word" else primary
    field = "path" if kind == "word" else "relpath"
    image_uri = index["images"][0][field]
    media = receipts[image_uri]
    assert raw[image_uri] == case.media[media["metadata"]["original_name"]]
    if image_format == "JPEG":
        assert raw[image_uri] == case.image_bytes
        assert media["mime_type"] == "image/jpeg"
    with tenant_scope(case.owner.tenant_id), workflow_file_snapshot(image_uri, context) as snapshot:
        assert snapshot.read_bytes() == raw[image_uri]
    if kind == "ppt":
        assert primary["slides"][0]["images"][0]["relpath"] == image_uri
        notes_uri = primary["reader_outputs"]["notes_output_path"]
        assert NOTES.encode() in raw[notes_uri]
        assert receipts[notes_uri]["name"] == "speaker_notes.txt"
        assert receipts[notes_uri]["metadata"]["original_name"] == "speaker_notes.md"
        assert receipts[notes_uri]["mime_type"] == "text/plain"
    for workspace in case.workspaces:
        assert str(workspace) not in json.dumps(result, ensure_ascii=False)


def test_media_receipts_reject_another_owner_and_wrong_mime(media_case, trusted_actor):
    from app.application.agent_orchestrator.artifact_files import read_verified_run_file
    from app.application.tools.workflow_spreadsheet_scope import (
        employee_output_receipts,
        workflow_file_snapshot,
    )

    case = media_case()
    result = case.execute()
    assert result["success"] is True, result
    image = next(row for row in result["artifacts"] if row["mime_type"] == "image/jpeg")
    other = trusted_actor(user_id=18, role="admin")
    context = {**case.context, **other.context, "node_outputs": {"reader": result}}
    with tenant_scope(other.tenant_id):
        with pytest.raises(PermissionError, match="账号|租户"):
            with workflow_file_snapshot(image["uri"], context):
                pytest.fail("another owner read the retained media")
        with pytest.raises(PermissionError, match="原调用"):
            employee_output_receipts("ppt-full-read-employee", result["data"], context)
    wrong = copy.deepcopy(image)
    wrong["mime_type"] = "image/png"
    with pytest.raises(ValueError, match="format or run mismatch"):
        read_verified_run_file(case.context["run_id"], wrong)


@pytest.mark.parametrize(
    "tamper", ["outside", "traversal", "symlink", "false_extension", "budget", "hidden_media"]
)
def test_media_preflight_rejects_unowned_or_invalid_files_before_publication(
    media_case, tmp_path, monkeypatch, tamper
):
    from app.application import excel_export_limits

    case = media_case()
    outside = tmp_path / "private.jpg"
    outside.write_bytes(case.image_bytes)

    def mutate(converted):
        if tamper == "hidden_media":
            converted.pop("meta_output_path")
            converted.pop("notes_output_path")
            return
        index_path = Path(converted["images_index_path"])
        index = json.loads(index_path.read_text())
        original = index["images"][0]["relpath"]
        path = index_path.parent / original
        if tamper == "budget":
            monkeypatch.setattr(excel_export_limits, "MAX_EXPORT_FILE_BYTES", 100)
            return
        if tamper == "outside":
            changed = str(outside)
        elif tamper == "traversal":
            changed = "../outputs/" + original
        elif tamper == "symlink":
            link = path.with_name("link.jpg")
            link.symlink_to(outside)
            changed = str(link.relative_to(index_path.parent))
        else:
            renamed = path.with_suffix(".png")
            path.rename(renamed)
            changed = str(renamed.relative_to(index_path.parent))
        index["images"][0]["relpath"] = changed
        index_path.write_text(json.dumps(index))

    case.mutate = mutate
    result = case.execute()
    assert result["success"] is False and not result.get("artifacts"), result
    assert case.published == []
    assert all(not path.exists() for path in [*case.workspaces, *case.originals])
    assert outside.read_bytes() == case.image_bytes and case.source.read_bytes() == case.content


def test_unhandled_media_format_is_blocked_without_dangling_paths(media_case):
    case = media_case(image_format="GIF")
    result = case.execute()
    assert result["success"] is False and not result.get("artifacts"), result
    assert "reader_media_format_unsupported" in str(result)
    assert case.published == []
    assert all(not path.exists() for path in [*case.workspaces, *case.originals])


def test_media_publication_failure_cleans_only_the_owned_staging(media_case, monkeypatch):
    from app.application.tools import workflow_spreadsheet_scope as scope

    case = media_case()
    store = scope.store_employee_output
    calls = []

    def fail_publication(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            raise OSError("media storage unavailable")
        return store(*args, **kwargs)

    monkeypatch.setattr(scope, "store_employee_output", fail_publication)
    with pytest.raises(OSError, match="media storage unavailable"):
        case.execute()
    assert len(calls) == 2
    assert all(not path.exists() for path in [*case.workspaces, *case.originals])
    assert case.source.read_bytes() == case.content
