from __future__ import annotations

from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore


def test_attendance_template_is_discovered_from_desktop_data_dir(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    tenant_templates = runtime_root / "tenants" / "424" / "templates"
    tenant_templates.mkdir(parents=True)
    template = tenant_templates / "考勤-2026-3月份考勤统计表.xlsx"
    template.write_bytes(b"PK test workbook")
    code_root = tmp_path / "code"
    code_root.mkdir()

    monkeypatch.setattr(
        "app.infrastructure.templates.template_store_impl.get_app_data_dir",
        lambda: str(runtime_root),
    )
    monkeypatch.setattr(
        "app.infrastructure.tenant_scope.current_tenant_id",
        lambda: 424,
    )
    store = FileSystemTemplateStore(str(code_root))

    items = store._discover_excel_templates()
    found = next(item for item in items if item["filename"] == template.name)
    assert found["template_type"] == "考勤记录"
    assert found["business_scope"] == "shipmentRecords"
    assert store.resolve_template_file(found["id"]) == str(template)
