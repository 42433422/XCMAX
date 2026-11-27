"""Exact native lookup through real owned uploads and the registered read tool."""

from __future__ import annotations

import hashlib
import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application import tabular_workbook as reader
from app.application.agent_orchestrator.tool_spec import (
    get_tool_action_spec,
    validate_schema_object,
)
from app.db.models.elt import EltUpload
from app.db.models.user import Session as UserSession
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_owned_document_fact_pages import owned_document as owned_document
from tests.test_application.test_owned_planner_attachments import (
    native_page_probes as native_page_probes,
)
from tests.test_infrastructure.test_workbook_page_index import _lookup_workbook, _match


@pytest.fixture
def uploaded_lookup(tmp_path, owned_document):
    from app.application.elt.service_uploads import register_chat_upload

    source = _lookup_workbook(tmp_path)
    body = source.read_bytes()
    actor = owned_document.actor
    saved = register_chat_upload(
        user=SimpleNamespace(id=actor.user_id, tenant_id=actor.tenant_id),
        filename=source.name,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        stream=io.BytesIO(body),
    )
    args = {
        "file_path": saved["upload_id"],
        "view": "cells",
        "sheet_name": "Data",
        "expected_sha256": saved["sha256"],
    }
    return SimpleNamespace(source=source, body=body, saved=saved, args=args, host=owned_document)


def test_registered_lookup_preserves_null_empty_and_whitespace_values(uploaded_lookup):
    fixture = uploaded_lookup
    spec = get_tool_action_spec("excel_analysis", "read")
    assert spec.read_only is True
    for match, address in [
        (_match("null", None, "blank"), "A4"),
        (_match("text", "", "empty_string"), "A3"),
        (_match("text", " \t "), "A7"),
        (_match("boolean", False), "A2"),
    ]:
        params = {**fixture.args, "value_match": match}
        assert validate_schema_object(spec.input_schema, params)[0] is True
        envelope, output, run = fixture.host.execute(params)
        assert envelope["success"] is True and output["success"] is True, (envelope, output)
        assert run.status == "completed" and run.user_id == str(fixture.host.actor.user_id)
        assert output["total_items"] == 1
        cell = output["cells"][0]
        assert cell["address"] == address
        assert {key: cell[key] for key in match} == match
        assert output["source_sha256"] == fixture.saved["sha256"]
    assert fixture.source.read_bytes() == fixture.body


def test_registered_lookup_pages_styles_sparse_locations_and_exact_readback(uploaded_lookup):
    fixture = uploaded_lookup
    params = {**fixture.args, "value_match": _match("number", 0), "max_rows": 1}
    _, first, _ = fixture.host.execute(params)
    assert first["success"] is True and first["total_items"] == 2
    assert first["cells"][0]["address"] == "A1"
    _, second, _ = fixture.host.execute(
        {**params, "offset": first["next_offset"], "cursor": first["next_cursor"]}
    )
    assert second["success"] is True and second["has_more"] is False
    far = second["cells"][0]
    assert far["address"] == "XFD1048576" and type(far["value"]) is int
    _, exact, _ = fixture.host.execute({**fixture.args, "cell_range": far["address"]})
    assert exact["cells"] == [far]
    _, selected_style, _ = fixture.host.execute({**fixture.args, "cell_range": "C1"})
    _, styled, _ = fixture.host.execute(
        {
            **fixture.args,
            "style_id": selected_style["cells"][0]["style_id"],
            "value_match": _match("text", "styled"),
            "cell_range": "C2:C3",
        }
    )
    assert styled["success"] is True and [cell["address"] for cell in styled["cells"]] == ["C2"]
    _, hidden, _ = fixture.host.execute({**params, "sheet_name": "Hidden"})
    assert hidden["success"] is True and hidden["cells"][0]["address"] == "XFD1048576"
    assert hidden["cells"][0]["source_ref"]["sheet"] == "Hidden"
    assert fixture.source.read_bytes() == fixture.body


@pytest.mark.parametrize("change", ["owner", "session_revoked", "replaced_snapshot"])
def test_registered_lookup_revalidates_authority_before_cached_page(
    uploaded_lookup, native_page_probes, change
):
    fixture = uploaded_lookup
    actor = fixture.host.actor
    params = {**fixture.args, "value_match": _match("number", 0), "max_rows": 1}
    first = fixture.host.route(params)
    assert first["success"] is True and first["has_more"] is True
    resume = {**params, "offset": first["next_offset"], "cursor": first["next_cursor"]}
    warm = fixture.host.route(resume)
    assert warm["success"] is True and native_page_probes.build.call_count == 1
    assert native_page_probes.actor.call_count == native_page_probes.upload.call_count == 2
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        if change == "session_revoked":
            db.delete(db.get(UserSession, actor.session_row_id))
        else:
            upload = db.get(EltUpload, fixture.saved["upload_id"])
            if change == "owner":
                upload.owner_user_id = 99
            else:
                changed = fixture.body + b"changed-source-version"
                from pathlib import Path

                # Upload copies are intentionally read-only. Simulate a server
                # publishing a new immutable revision by atomic replacement.
                replacement = Path(upload.storage_path).with_suffix(".replacement.xlsx")
                replacement.write_bytes(changed)
                replacement.replace(upload.storage_path)
                upload.sha256, upload.size_bytes = hashlib.sha256(changed).hexdigest(), len(changed)
    denied = fixture.host.route(resume)
    assert denied["success"] is False and "cells" not in denied
    assert native_page_probes.build.call_count == 1
    assert native_page_probes.actor.call_count == 3
    if change == "replaced_snapshot":
        assert "SHA-256 mismatch" in denied["message"]


@pytest.mark.parametrize("mutation", ["missing_value", "wrong_type", "extra_field"])
def test_registered_input_contract_rejects_incomplete_or_invalid_typed_match(
    uploaded_lookup, mutation
):
    fixture = uploaded_lookup
    match = _match("number", 0)
    if mutation == "missing_value":
        match.pop("value")
    elif mutation == "wrong_type":
        match["value"] = False
    else:
        match["source_scope"] = "model-forged-scope"
    params = {**fixture.args, "value_match": match}
    assert (
        validate_schema_object(get_tool_action_spec("excel_analysis", "read").input_schema, params)[
            0
        ]
        is False
    )
    _, output, _ = fixture.host.execute(params)
    assert output["success"] is False and "cells" not in output


def test_registered_lookup_never_silently_applies_to_dense_or_noncell_views(uploaded_lookup):
    fixture = uploaded_lookup
    for view in ("table", "sheets"):
        result = fixture.host.route(
            {**fixture.args, "view": view, "value_match": _match("number", 0)}
        )
        assert result["success"] is False
        assert result["error"] == "native_lookup_requires_cells_read"


def test_lookup_without_bound_host_scope_cannot_consume_the_scoped_cache(
    uploaded_lookup, native_page_probes
):
    fixture = uploaded_lookup
    params = {**fixture.args, "value_match": _match("number", 0), "max_rows": 1}
    scoped = fixture.host.route(params)
    with pytest.raises(ValueError, match="native_lookup_cursor_selection_changed"):
        reader.read_workbook_page(
            fixture.source,
            view="cells",
            sheet_name="Data",
            expected_sha256=fixture.saved["sha256"],
            value_match=params["value_match"],
            offset=scoped["next_offset"],
            cursor=scoped["next_cursor"],
        )
    assert native_page_probes.build.call_count == 1


@pytest.mark.parametrize(
    "selector",
    [
        {"value_match": _match("text", "not-in-source")},
        {"style_id": "native-style-id"},
        {"value_match": {}},
        {"style_id": ""},
    ],
    ids=["value", "style", "empty-match", "empty-style"],
)
def test_nonexcel_registered_read_rejects_excel_selectors_before_parsing(
    owned_document, monkeypatch, selector
):
    from app.application import tabular_document

    raw = b"name,value\nkept,0\n"
    original, saved = owned_document.upload(".csv", raw)
    params = {
        "file_path": saved["upload_id"],
        "view": "cells",
        "expected_sha256": saved["sha256"],
        **selector,
    }
    spec = get_tool_action_spec("excel_analysis", "read")
    schema_allowed = validate_schema_object(spec.input_schema, params)[0]
    _, result, _ = owned_document.execute(params)
    assert result["success"] is False, result
    assert "cells" not in result and "data" not in result
    if schema_allowed:
        assert result["error_code"] == "document_argument_not_supported"
        assert result["status"] == "blocked"
    # The existing owned snapshot is still acquired; an unsupported selector
    # must never reach a non-Excel parser, including explicitly empty values.
    parse = Mock(wraps=tabular_document.read_document_facts)
    monkeypatch.setattr(tabular_document, "read_document_facts", parse)
    routed = owned_document.route(params)
    assert routed["success"] is False and routed["status"] == "blocked"
    assert routed["error_code"] == "document_argument_not_supported"
    assert parse.call_count == 0
    assert original.read_bytes() == raw
