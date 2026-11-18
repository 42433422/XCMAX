"""模板库清理：内置模板改为按租户隐藏，清理后列表不再出现。"""

from unittest.mock import MagicMock, patch

from app.application.starter_template_catalog import merge_starter_templates
from app.domain.shared_services.tools_workflow_shipments_docs_ops import (
    _registered_router_document_template,
)
from app.infrastructure.templates import template_preferences
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_hide_templates_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(template_preferences, "get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(template_preferences, "current_tenant_id", lambda: 1)

    assert (
        template_preferences.hide_templates(
            ids=["seed:sales-order"], paths=["/opt/templates/标准发货单.xlsx"]
        )
        == 2
    )
    assert template_preferences.hidden_template_ids() == {"seed:sales-order"}
    assert template_preferences.hidden_template_paths() == {"/opt/templates/标准发货单.xlsx"}
    # 重复隐藏不重复计数
    assert template_preferences.hide_templates(ids=["seed:sales-order"]) == 0


def test_merge_starter_templates_skips_hidden(monkeypatch):
    monkeypatch.setattr(template_preferences, "hidden_template_ids", lambda: {"seed:sales-order"})
    rows = merge_starter_templates([])
    assert rows and all(row["id"] != "seed:sales-order" for row in rows)


def test_clear_hides_builtin_templates_instead_of_failing(trusted_actor):
    actor = trusted_actor()
    listed = {
        "templates": [
            {"id": "seed:sales-order", "name": "销售订单标准表"},
            {
                "id": "fs:标准发货单.xlsx",
                "name": "标准发货单",
                "path": "/opt/templates/标准发货单.xlsx",
            },
            {"id": "db:7", "name": "自定义模板"},
        ]
    }
    service = MagicMock()
    service.get_templates.return_value = listed
    service.purge_archive_assets.return_value = 0
    captured: dict = {}

    def fake_delete(payload, base_dir=None):
        if payload["id"] == "db:7":
            return {"success": True}, 200
        return {"success": False, "message": "内置模板不可删除"}, 403

    def fake_hide(*, ids=None, paths=None):
        captured["ids"] = list(ids or [])
        captured["paths"] = list(paths or [])
        return len(captured["ids"]) + len(captured["paths"])

    service.hide_templates.side_effect = fake_hide
    with (
        patch("app.application.get_template_app_service", return_value=service),
        patch(
            "app.legacy.routes.document_templates_compat.run_archive_template_delete",
            side_effect=fake_delete,
        ),
        patch.object(template_preferences, "hide_templates", return_value=0) as legacy_hide,
    ):
        result = _registered_router_document_template("clear", {}, actor.context, "", "")

    assert result["success"] is True
    assert result["deleted_templates"] == 1
    assert result["hidden_templates"] == 2
    assert captured["ids"] == ["seed:sales-order"]
    assert captured["paths"] == ["/opt/templates/标准发货单.xlsx"]
    assert "已清理 1 个自定义模板" in result["message"]
    legacy_hide.assert_not_called()
    service.purge_archive_assets.assert_called_once_with(tenant_id=7, owner_id=actor.user_id)
