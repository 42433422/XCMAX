"""employee_pack → Planner 工具注册表。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_employee_list_matches_the_declared_tool_result(employee_mods_root):
    from app.application.agent_orchestrator.tool_spec import validate_tool_result
    from app.domain.shared_services.tools_workflow_workspace import _registered_router_employee

    _write_csv_read_pack(employee_mods_root)
    result = _registered_router_employee("list", {}, {}, "normal", "有哪些员工")
    assert validate_tool_result("employee", "list", result).ok
    assert any(item["employee_id"] == "csv-full-read-employee" for item in result["data"])


def test_sales_filter_contract_rejects_invented_state_field():
    from app.application.agent_orchestrator.tool_spec import validate_tool_call

    assert validate_tool_call(
        "sales", "query", {"status": "confirmed", "customer_name": "客户甲"}
    ).ok
    assert not validate_tool_call("sales", "query", {"order_state": "confirmed"}).ok


def _write_csv_read_pack(root: Path, pack_id: str = "csv-full-read-employee") -> Path:
    pack_dir = root / "_employees" / pack_id
    vendor = pack_dir / "backend" / "vendor" / "csv_read"
    vendor.mkdir(parents=True, exist_ok=True)
    (pack_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": pack_id,
                "name": "CSV 读取员工",
                "artifact": "employee_pack",
                "scope": "global",
                "description": "读取 CSV 表格",
                "employee": {"label": "CSV 读取"},
                "employee_config_v2": {
                    "actions": {
                        "handlers": ["direct_python"],
                        "direct_python": {"module": "worker"},
                    },
                    "cognition": {"agent": {"system_prompt": "读取 CSV 文件并返回结构化数据"}},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (pack_dir / "rule_spec.json").write_text(
        json.dumps(
            {
                "runtime_kind": "csv_full_read",
                "default_output_relpath": "outputs/data.json",
                "output_schema": ["columns", "rows"],
            }
        ),
        encoding="utf-8",
    )
    (vendor / "convert.py").write_text(
        """from pathlib import Path

def convert_file(src_path, output_path, *, template_path=None, payload=None, ctx=None, rule_spec=None):
    text = Path(src_path).read_text(encoding='utf-8')
    lines = [l for l in text.strip().splitlines() if l]
    cols = lines[0].split(',') if lines else []
    rows = [dict(zip(cols, ln.split(','))) for ln in lines[1:]]
    out = {"columns": cols, "rows": rows, "row_count": len(rows)}
    Path(output_path).write_text(__import__('json').dumps(out), encoding='utf-8')
    return {"output_path": str(output_path), "row_count": len(rows), "column_count": len(cols)}
""",
        encoding="utf-8",
    )
    from app.infrastructure.mods.package import compute_directory_hash

    receipt = {
        "schema_version": 1,
        "signature_verified": True,
        "content_sha256": compute_directory_hash(str(pack_dir)),
    }
    (pack_dir / ".xcagi-install-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return pack_dir


@pytest.fixture()
def employee_mods_root(tmp_path, monkeypatch):
    mods_root = tmp_path / "mods"
    mods_root.mkdir()
    catalog = "xcagi-office-employee-pack-bridge"
    from app.mod_sdk.mod_source_paths import mod_source_dir

    source = mod_source_dir(catalog) or (Path(__file__).parents[1] / "mods" / catalog)
    shutil.copytree(source, mods_root / catalog)
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(mods_root))
    from app.application.tools.workflow import invalidate_workflow_tool_registry
    from app.infrastructure.mods import employee_registry as er
    from app.infrastructure.mods import mod_manager as mm
    from app.infrastructure.mods.registry import ModRegistry

    monkeypatch.setattr(ModRegistry, "_instance", None)
    er._registry.clear()
    monkeypatch.setattr(mm, "_mod_manager", None)
    mm._employee_pack_routes_registered.clear()
    invalidate_workflow_tool_registry()
    return mods_root


def test_planner_registry_includes_installed_employee_pack(employee_mods_root):
    pack_id = "csv-full-read-employee"
    _write_csv_read_pack(employee_mods_root, pack_id)

    from app.mod_sdk.employee_tool_registry import (
        build_employee_pack_tool_definitions,
        invalidate_employee_tool_cache,
    )

    invalidate_employee_tool_cache()
    tools = build_employee_pack_tool_definitions()
    names = [t["function"]["name"] for t in tools]
    assert pack_id in names


def test_execute_employee_csv_read_tool(employee_mods_root, tmp_path, monkeypatch, trusted_actor):
    from io import BytesIO

    from app.application.elt.service import get_elt_service
    from app.domain.shared_services.tools_workflow_workspace import _registered_router_employee
    from app.infrastructure.tenant_scope import tenant_scope
    from app.mod_sdk.employee_tool_registry import invalidate_employee_tool_cache

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    pack_id = "csv-full-read-employee"
    _write_csv_read_pack(employee_mods_root, pack_id)
    invalidate_employee_tool_cache()
    owner, other = trusted_actor(user_id=7), trusted_actor(user_id=8)
    with tenant_scope(owner.tenant_id), owner.factory.begin() as db:
        upload = get_elt_service().save_upload(
            db,
            owner_user_id=owner.user_id,
            file_name="sample.csv",
            content_type="text/csv",
            stream=BytesIO(b"a,b\n1,2\n3,4\n"),
        )
    target = tmp_path / "foreign.csv"
    params = {
        "employee_id": "csv_full_read",
        "task": "读取表格",
        "input": {
            "upload_id": upload["upload_id"],
            "template_relpath": str(target),
            "output_relpath": str(target),
            "workspace_root": str(tmp_path),
        },
    }
    with tenant_scope(owner.tenant_id):
        allowed = _registered_router_employee("execute", params, owner.context, "normal", "")
        denied = _registered_router_employee("execute", params, other.context, "normal", "")
    assert allowed["success"], allowed
    assert Path(allowed["data"]["file_path"]).is_file()
    assert denied["data"]["error_code"] == "employee_file_access_denied"
    assert not target.exists()
    from app.application.employee_runtime import executor

    def no_file_worker(*args, **kwargs):
        pytest.fail("context-only must not execute the file worker")

    monkeypatch.setattr(executor, "_action_direct_python_module", no_file_worker)
    context_params = {"employee_id": "csv_full_read", "task": "提供上游上下文"}

    def call(action, context, **inputs):
        return _registered_router_employee(
            action, {**context_params, "input": inputs}, context, "normal", ""
        )

    assert call("context", owner.context)["success"]
    viewer = trusted_actor(user_id=9, role="viewer", permissions=["customer.view"])
    for context in (viewer.context, {**owner.context, "tenant_id": "999"}):
        assert call("context", context)["data"]["error_code"] in {
            "tool_permission_denied",
            "tool_identity_required",
        }
    target.write_text("private\nsecret\n")
    for action in ("execute", "context"):
        denied = call(
            action, owner.context, invoke_mode="collaboration_context", file_path=str(target)
        )
        assert denied["data"]["error_code"] == "employee_file_access_denied"
    assert target.read_text() == "private\nsecret\n"
    for key in (
        "template_path",
        "template_relpath",
        "output_path",
        "output_relpath",
        "workspace_root",
    ):
        denied = call("context", owner.context, **{key: str(target)})
        assert denied["data"]["error_code"] == "employee_file_access_denied"
    for flag in (False, True):
        denied = call(
            "execute",
            {**owner.context, "employee_collaboration_run": flag},
            invoke_mode="collaboration_context",
        )
        assert denied["data"]["error_code"] == "employee_file_access_denied"


def test_office_employee_never_reports_success_without_artifact(employee_mods_root, monkeypatch):
    """A direct Python return is insufficient when the promised output is absent."""
    pack_id = "csv-full-read-employee"
    _write_csv_read_pack(employee_mods_root, pack_id)

    from app.application.employee_runtime import executor
    from app.mod_sdk import employee_tool_registry as registry
    from app.mod_sdk.employee_pack_compat import list_office_pack_catalog

    assert pack_id in list_office_pack_catalog()["pack_ids"]
    missing_output = employee_mods_root / "missing-output.csv"
    assert not missing_output.exists()

    registry.invalidate_employee_tool_cache()
    monkeypatch.setattr(
        executor,
        "execute_employee_task_local",
        lambda *_args, **_kwargs: {
            "success": True,
            "result": {
                "outputs": [
                    {
                        "handler": "direct_python",
                        "ok": True,
                        "output_path": str(missing_output),
                    }
                ]
            },
        },
    )

    data = json.loads(registry.execute_employee_tool(pack_id, {"file_path": "x.csv"}))

    assert data["success"] is False
    assert data["artifact_postcondition"]["verified"] is False
    assert "输出文件" in data["error"]


def test_get_planner_chat_tool_registry_merges_employee_tools(employee_mods_root):
    _write_csv_read_pack(employee_mods_root)
    from app.application.tools.workflow import invalidate_workflow_tool_registry
    from app.mod_sdk.planner_tools import get_planner_chat_tool_registry

    invalidate_workflow_tool_registry()
    reg = get_planner_chat_tool_registry()
    names = [item["function"]["name"] for item in reg if item.get("function")]
    assert "csv-full-read-employee" in names


def test_legacy_tool_alias_still_resolves(employee_mods_root):
    _write_csv_read_pack(employee_mods_root)
    from app.mod_sdk.employee_tool_registry import (
        invalidate_employee_tool_cache,
        pack_id_to_legacy_tool_name,
        resolve_tool_to_pack_id,
    )

    invalidate_employee_tool_cache()
    legacy = pack_id_to_legacy_tool_name("csv-full-read-employee")
    assert resolve_tool_to_pack_id(legacy) == "csv-full-read-employee"


def test_employee_tools_status_counts(employee_mods_root):
    _write_csv_read_pack(employee_mods_root)
    from app.mod_sdk.employee_tool_registry import (
        build_employee_tools_status,
        invalidate_employee_tool_cache,
    )

    invalidate_employee_tool_cache()
    status = build_employee_tools_status()
    assert status["installed_employee_pack_count"] >= 1
    assert status["registered_tool_count"] >= 1


def test_seeded_employee_cache_uses_trusted_source_without_trusting_modified_code(
    tmp_path, monkeypatch
):
    from app.application.employee_runtime import loader

    installed, bundled = tmp_path / "installed", tmp_path / "bundled"
    for root in (installed, bundled):
        pack = root / "test-worker"
        pack.mkdir(parents=True)
        (pack / "manifest.json").write_text("{}")
        (pack / "worker.py").write_text("def run(): return 1")
    cache = installed / "test-worker" / "__pycache__"
    cache.mkdir()
    (cache / "worker.pyc").write_bytes(b"cache")
    monkeypatch.setattr(loader, "_employee_roots", lambda: [installed, bundled])
    monkeypatch.setattr(
        loader, "verify_direct_python_pack_trust", lambda path: (path.parent == bundled, "source")
    )
    assert loader.resolve_pack_dir("test-worker") == bundled / "test-worker"
    (installed / "test-worker" / "worker.py").write_text("def run(): return 2")
    assert loader.resolve_pack_dir("test-worker") == installed / "test-worker"


@pytest.mark.parametrize("count,total,ok", [(2, 200, True), (1, 200, False), (2, 201, False)])
def test_excel_verification_rejects_incorrect_count_or_total(monkeypatch, count, total, ok):
    from app.domain.shared_services.tools_workflow_excel_ocr import (
        _registered_router_excel_analysis,
    )

    monkeypatch.setattr(
        "app.application.tools.workflow.handle_excel_analysis",
        lambda *a, **kw: {
            "success": True,
            "row_count": 2,
            "numeric_summary": {"total_amount": {"sum": 200}},
        },
    )
    result = _registered_router_excel_analysis(
        "statistics",
        {
            "file_path": "report.xlsx",
            "expected_row_count": count,
            "expected_totals": {"total_amount": total},
        },
        {},
        "normal",
        "",
    )
    assert result["success"] is ok and result["verification"]["verified"] is ok


def test_excel_verification_accepts_amount_as_total_amount(monkeypatch):
    from app.domain.shared_services.tools_workflow_excel_ocr import (
        _registered_router_excel_analysis,
    )

    monkeypatch.setattr(
        "app.application.tools.workflow.handle_excel_analysis",
        lambda *a, **kw: {
            "success": True,
            "row_count": 1,
            "numeric_summary": {"amount": {"sum": 200}, "quantity": {"sum": 2}},
        },
    )
    result = _registered_router_excel_analysis(
        "statistics",
        {
            "file_path": "report.xlsx",
            "expected_row_count": 1,
            "expected_totals": {"total_amount": 200},
        },
        {},
        "normal",
        "",
    )
    assert result["success"] is True and result["verification"]["verified"] is True


@pytest.mark.parametrize(
    "action,suffix",
    [("context", "pdf"), *(("execute", ext) for ext in ("pdf", "csv", "docx", "pptx", "xlsx"))],
)
def test_employee_workflow_hands_off_the_declared_deliverable(
    tmp_path, monkeypatch, trusted_actor, action, suffix
):
    from app.application.employee_runtime import executor
    from app.application.tools.workflow_spreadsheet_scope import workflow_file_snapshot
    from app.domain.shared_services.tools_workflow_workspace import _registered_router_employee
    from app.infrastructure.tenant_scope import tenant_scope

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    document = tmp_path / f"report.{suffix}"
    content = b"amount\n200\n" if suffix == "csv" else b"office fixture"
    if suffix in {"pdf", "docx", "pptx"}:
        from tests.test_application.test_pr3126_office_receipts import office_bytes

        content = office_bytes(suffix)
    document.write_bytes(content)
    output = (
        {"output": "上游文本"}
        if action == "context"
        else {
            "output_path": str(tmp_path / "parsed.json"),
            "output": {"document_output_path": str(document)},
        }
    )
    monkeypatch.setattr(
        executor,
        "execute_employee_task_local",
        lambda *a, **kw: {"success": True, "result": {"outputs": [output]}},
    )
    employee = {"docx": "word", "pptx": "ppt"}.get(suffix, suffix)
    employee_id = f"{employee}-generate-employee" if suffix != "xlsx" else "test-worker"
    if suffix == "xlsx":
        output.pop("output_path", None)
    owner = trusted_actor(user_id=7)
    context = {**owner.context, "workspace_root": str(tmp_path), "run_id": "run_handoff"}
    params = {"employee_id": employee_id, "task": "协作"}
    result = _registered_router_employee(action, params, context, "normal", "")
    assert result["success"]
    assert result["data"].get("file_path") == (str(document) if action == "execute" else None)
    assert len(result["artifacts"]) == int(action == "execute")
    if action == "execute":
        context["node_outputs"] = {"employee": result}
        document.unlink()
        with (
            tenant_scope(owner.tenant_id),
            workflow_file_snapshot(str(document), context) as staged,
        ):
            assert staged.suffix == "." + suffix and staged.read_bytes() == content
        with pytest.raises(OSError):
            _registered_router_employee(action, params, context, "normal", "")


@pytest.mark.parametrize("suffix", ["xlsx", "csv"])
def test_workflow_spreadsheet_receipts(tmp_path, monkeypatch, trusted_actor, suffix):
    from io import BytesIO

    from app.application.agent_orchestrator.artifact_files import artifact_path
    from app.application.elt.service import get_elt_service
    from app.db.models.elt import EltUpload
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
        original = db.get(EltUpload, upload["upload_id"]).storage_path

    copy = {"file_path": "uploads/chat-copy.csv", "upload_id": upload["upload_id"]}
    context = {**owner.context, "run_id": "run_owner", "excel_analysis": copy}

    def tool(action, params, ctx=context, tenant=owner.tenant_id):
        with tenant_scope(tenant):
            return _registered_router_excel_analysis(action, params, ctx, "normal", "")

    for args in ({}, {"file_path": original}):
        stats = tool("statistics", args)
        assert stats["row_count"] == 2 and stats["numeric_summary"]["amount"]["sum"] == 200
    for args, ctx, tenant in (
        ({}, {**other.context, "excel_analysis": copy}, owner.tenant_id),
        ({"file_path": "/unrelated.csv"}, context, owner.tenant_id),
        ({}, context, 999),
    ):
        assert tool("statistics", args, ctx, tenant)["error_code"] == "spreadsheet_access_denied"

    filename = f"sales.{suffix}"
    params = {"file_path": filename, "rows": [{"amount": 120}, {"amount": 80}]}
    exported = tool("export", params)
    receipt = exported["artifacts"][0]
    uri = {"file_path": receipt["uri"]}
    artifact = artifact_path("run_owner", receipt["artifact_id"])
    assert exported["success"] and exported["data"]["file_path"] == uri["file_path"]
    assert receipt["name"] == filename and artifact.suffix == "." + suffix
    assert tool("statistics", uri)["error_code"] == "spreadsheet_access_denied"
    context["node_outputs"] = {"export": exported}
    stats = tool("statistics", uri)
    assert stats["row_count"] == 2 and stats["numeric_summary"]["amount"]["sum"] == 200
    assert not tool("statistics", uri, {**context, "run_id": "different-run"})["success"]
    artifact.write_bytes(b"changed")
    assert "checksum" in tool("statistics", uri)["message"]

    def unavailable(*args, **kwargs):
        raise OSError("receipt storage unavailable")

    monkeypatch.setattr(
        "app.application.tools.workflow_spreadsheet_scope.store_spreadsheet", unavailable
    )
    failed = tool("export", params)
    assert not failed["success"] and not failed.get("artifacts")


@pytest.mark.parametrize(
    "role,tier,tenant",
    [("user", "enterprise", 7), ("operator", "enterprise", 7), ("admin", "admin", None)],
)
def test_host_employee_capabilities_require_platform_admin(
    trusted_actor, monkeypatch, tmp_path, role, tier, tenant
):
    from app.application.employee_runtime.agent import EmployeeAgent
    from app.application.employee_runtime.executor import execute_employee_task_local

    actor = trusted_actor(user_id=21, role=role, tier=tier, tenant_id=tenant)
    marker = tmp_path / "must-not-run"
    exploit = {
        "handler": "specialized",
        "tool": "sandbox_python",
        "params": {
            "code": f"open({str(marker)!r}, 'w').write('unsafe')",
            "confirm": True,
        },
    }
    observed = []
    monkeypatch.setattr(
        EmployeeAgent, "run", lambda *a, **kw: observed.append(a) or {"success": True}
    )
    for employee, payload in (
        ("artifact-generator", exploit),
        ("artifact_generator", {}),
        ("excel-generate-employee", exploit),
    ):
        result = execute_employee_task_local(
            employee, "执行", payload, runtime_context=actor.context
        )
        assert result["success"] is (role == "admin")
        if role != "admin":
            assert result["error_code"] == "employee_host_admin_required"
    assert len(observed) == (3 if role == "admin" else 0) and not marker.exists()
    assert execute_employee_task_local(
        "excel-generate-employee",
        "生成报表",
        {"table_json": {"rows": []}},
        runtime_context=actor.context,
    )["success"]
