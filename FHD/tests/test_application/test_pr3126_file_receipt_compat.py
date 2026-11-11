from io import BytesIO

import pytest

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_chat_workspace_copy_uses_owned_immutable_upload(tmp_path, monkeypatch, trusted_actor):
    from app.application.elt.service import get_elt_service
    from app.domain.shared_services.tools_workflow_excel_ocr import (
        _registered_router_excel_analysis,
    )
    from app.infrastructure.tenant_scope import tenant_scope

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    owner, other = trusted_actor(user_id=7), trusted_actor(user_id=8)
    with tenant_scope(owner.tenant_id), owner.factory.begin() as db:
        upload = get_elt_service().save_upload(
            db,
            owner_user_id=owner.user_id,
            file_name="orders.csv",
            content_type="text/csv",
            stream=BytesIO(b"amount\n120\n80\n"),
        )
    copy = str(tmp_path / "uploads" / "workspace-copy.csv")
    excel = {"file_path": copy, "upload_id": upload["upload_id"]}
    with tenant_scope(owner.tenant_id):
        result = _registered_router_excel_analysis(
            "statistics", {}, {**owner.context, "excel_analysis": excel}, "normal", ""
        )
        assert result["numeric_summary"]["amount"]["sum"] == 200
        assert result["row_count"] == 2
        for context, path in [
            ({**other.context, "excel_analysis": excel}, copy),
            ({**owner.context, "excel_analysis": excel}, "/unrelated.csv"),
        ]:
            denied = _registered_router_excel_analysis(
                "statistics", {"file_path": path}, context, "normal", ""
            )
            assert denied["error_code"] == "spreadsheet_access_denied"
    with tenant_scope(999):
        denied = _registered_router_excel_analysis(
            "statistics", {}, {**owner.context, "excel_analysis": excel}, "normal", ""
        )
        assert denied["error_code"] == "spreadsheet_access_denied"


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_export_then_statistics_uses_verified_run_receipt(
    tmp_path, monkeypatch, trusted_actor, suffix
):
    from app.application.agent_orchestrator.artifact_files import artifact_path
    from app.domain.shared_services.tools_workflow_excel_ocr import (
        _registered_router_excel_analysis,
    )
    from app.infrastructure.tenant_scope import tenant_scope

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    owner = trusted_actor(user_id=7)
    context = {
        **owner.context,
        "run_id": "run-export",
        "workspace_root": str(tmp_path / "temp_excel" / "workspace"),
    }
    with tenant_scope(owner.tenant_id):
        exported = _registered_router_excel_analysis(
            "export",
            {"file_path": f"output.{suffix}", "rows": [{"amount": 120}, {"amount": 80}]},
            context,
            "normal",
            "",
        )
        assert exported["success"] is True
        receipt = exported["artifacts"][0]
        assert receipt["artifact_id"].startswith(suffix + "_")
        assert artifact_path("run-export", receipt["artifact_id"]).suffix == "." + suffix
        context["node_outputs"] = {"export": exported}
        for path in [exported["data"]["file_path"], receipt["uri"]]:
            result = _registered_router_excel_analysis(
                "statistics", {"file_path": path}, context, "normal", ""
            )
            assert result["row_count"] == 2
            assert result["numeric_summary"]["amount"]["sum"] == 200
        # An unrelated run cannot borrow the receipt even when given the output dict.
        denied = _registered_router_excel_analysis(
            "statistics",
            {"file_path": exported["data"]["file_path"]},
            {**context, "run_id": "different-run"},
            "normal",
            "",
        )
        assert denied["success"] is False
        artifact_path("run-export", receipt["artifact_id"]).write_bytes(b"changed")
        denied = _registered_router_excel_analysis(
            "statistics", {"file_path": receipt["uri"]}, context, "normal", ""
        )
        assert denied["success"] is False
        assert "checksum" in denied["message"]


def test_export_receipt_failure_does_not_claim_verified_success(
    tmp_path, monkeypatch, trusted_actor
):
    from app.application.agent_orchestrator import artifact_files
    from app.domain.shared_services.tools_workflow_excel_ocr import (
        _registered_router_excel_analysis,
    )
    from app.infrastructure.tenant_scope import tenant_scope

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    owner = trusted_actor(user_id=7)

    def unavailable(*args, **kwargs):
        raise OSError("receipt storage unavailable")

    monkeypatch.setattr(
        "app.application.tools.workflow_spreadsheet_scope.store_spreadsheet", unavailable
    )
    with tenant_scope(owner.tenant_id):
        result = _registered_router_excel_analysis(
            "export",
            {"file_path": "output.csv", "rows": [{"amount": 200}]},
            {
                **owner.context,
                "run_id": "run-export",
                "workspace_root": str(tmp_path / "temp_excel" / "workspace"),
            },
            "normal",
            "",
        )
    assert result["success"] is False
    assert not result.get("artifacts")
