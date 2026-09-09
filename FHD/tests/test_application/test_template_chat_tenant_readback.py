"""Real SQLite template rows survive the ordinary-chat service chain by tenant."""

from contextlib import contextmanager
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.application.normal_chat_dispatch import try_normal_slot_read_payload
from app.application.template_app_service import TemplateApplicationService
from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore


def test_chat_template_readback_isolated_by_request_tenant(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'templates.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text('''CREATE TABLE templates (
            id INTEGER PRIMARY KEY, template_key TEXT, template_name TEXT,
            template_type TEXT, original_file_path TEXT, is_active INTEGER,
            tenant_id INTEGER, analyzed_data TEXT, editable_config TEXT, business_rules TEXT
        )'''))
        connection.execute(text('''INSERT INTO templates
            (id, template_name, template_type, is_active, tenant_id)
            VALUES (1, '甲方专用单据', '发货单', 1, 11),
                   (2, '乙方专用单据', '发货单', 1, 22),
                   (3, '未归属历史单据', '发货单', 1, NULL),
                   (4, '甲方停用单据', '发货单', 0, 11)'''))

    @contextmanager
    def database():
        with Session(engine) as session:
            yield session

    monkeypatch.setenv("XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE", "0")
    monkeypatch.setattr("app.infrastructure.templates.template_store_impl.get_db", database)
    # Schema is already created here; runtime migration is a separate acceptance gate.
    monkeypatch.setattr("app.infrastructure.templates.tenant_scope.ensure_templates_tenant_column", lambda: None)
    monkeypatch.setattr("app.infrastructure.templates.template_discovery.get_app_data_dir", lambda: str(tmp_path))
    service = TemplateApplicationService(FileSystemTemplateStore(str(tmp_path / "builtins")))
    monkeypatch.setattr("app.application.get_template_app_service", lambda: service)
    try:
        for tenant, expected in [(11, {"db:1"}), (22, {"db:2"}), (None, set())]:
            request = SimpleNamespace(state=SimpleNamespace(tenant_id=tenant))
            response = try_normal_slot_read_payload("模板预览", request=request)
            assert response["success"]
            records = response["data"]["templates"]
            assert {row["id"] for row in records if row.get("source") == "db"} == expected
            assert "未归属历史单据" not in response["response"]
            assert "甲方停用单据" not in response["response"]
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM templates")).scalar_one() == 4
    finally:
        engine.dispose()
