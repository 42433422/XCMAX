"""
模板应用服务

负责模板管理相关的用例编排
"""

from typing import Any, cast

from app.application.starter_template_catalog import merge_starter_templates
from app.di.registry import get_service_registry


def persist_workflow_preview_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist an analyzed preview with tenancy enforced at the application boundary."""
    from sqlalchemy import text

    from app.db.session import get_db
    from app.infrastructure.templates.tenant_scope import templates_tenant_id_for_insert
    from app.infrastructure.tenant_scope import TenantScopeError

    try:
        tenant_id = templates_tenant_id_for_insert()
    except TenantScopeError:
        return {"success": False, "message": "缺少租户上下文，无法创建模板"}
    with get_db() as db:
        result = db.execute(
            text(
                "\n                    INSERT INTO templates (\n                        template_key, template_name, template_type,\n                        original_file_path, analyzed_data, editable_config,\n                        zone_config, merged_cells_config, style_config,\n                        business_rules, is_active, tenant_id\n                    ) VALUES (\n                        :template_key, :template_name, :template_type,\n                        :original_file_path, :analyzed_data, :editable_config,\n                        :zone_config, :merged_cells_config, :style_config,\n                        :business_rules, :is_active, :tenant_id\n                    )\n                "
            ),
            {**payload, "tenant_id": tenant_id},
        )
        template_id = result.lastrowid
        db.commit()
    return {"success": True, "template_id": template_id}


class TemplateApplicationService:
    """模板应用服务 - 负责模板相关的用例编排"""

    def __init__(
        self,
        template_service=None,
    ):
        self._template_service = template_service

    def get_templates(
        self, category: str | None = None, tenant_id: int | None = None
    ) -> dict[str, Any]:
        """
        获取模板列表用例

        Args:
            category: 模板分类
            tenant_id: 后台执行时显式携带的租户

        Returns:
            模板列表
        """
        from app.application.reviewed_excel_template_blocks import collapse_listed_templates
        from app.infrastructure.tenant_scope import tenant_scope

        with tenant_scope(tenant_id):
            if category and category != "all":
                rows = self._template_service.list_by_type(category) or []
                return {
                    "templates": collapse_listed_templates(merge_starter_templates(rows, category))
                }
            rows = self._template_service.list_templates() or []
            return {"templates": collapse_listed_templates(merge_starter_templates(rows))}

    def hide_templates(self, *, ids: list[str], paths: list[str]) -> int:
        from app.infrastructure.templates.template_preferences import hide_templates

        return hide_templates(ids=ids, paths=paths)

    def purge_archive_assets(
        self, *, tenant_id: int | None = None, owner_id: int | None = None
    ) -> int:
        """仅清理指定账号与租户的审阅归档资产；显式值优先于当前请求。"""
        from app.application.elt.errors import EltError
        from app.db.models.elt_archive import EltArchiveAsset, EltArchiveVersion
        from app.db.session import get_db
        from app.domain.context.current_request import get_current_request
        from app.infrastructure.tenant_scope import tenant_scope

        request = get_current_request()
        user = getattr(getattr(request, "state", None), "user", None)
        tenant = int(tenant_id or getattr(user, "tenant_id", None) or 0)
        owner = int(owner_id or getattr(user, "id", None) or 0)
        if not tenant or not owner:
            return 0
        try:
            with tenant_scope(tenant), get_db() as db:
                asset_ids = [
                    row[0]
                    for row in db.query(EltArchiveAsset.id)
                    .filter(
                        EltArchiveAsset.tenant_id == tenant,
                        EltArchiveAsset.owner_user_id == owner,
                    )
                    .all()
                ]
                if not asset_ids:
                    return 0
                db.query(EltArchiveVersion).filter(
                    EltArchiveVersion.tenant_id == tenant,
                    EltArchiveVersion.asset_id.in_(asset_ids),
                ).delete(synchronize_session=False)
                removed = (
                    db.query(EltArchiveAsset)
                    .filter(
                        EltArchiveAsset.tenant_id == tenant,
                        EltArchiveAsset.owner_user_id == owner,
                    )
                    .delete(synchronize_session=False)
                )
                db.commit()
                return int(removed or 0)
        except (EltError, RuntimeError, ValueError):
            return 0

    def get_template(self, template_id: int) -> dict[str, Any]:
        """
        获取单个模板用例

        Args:
            template_id: 模板 ID

        Returns:
            模板信息
        """
        return cast("dict[str, Any]", self._template_service.get_template(template_id))

    def list_by_type(self, template_type: str, active_only: bool = True) -> list[dict[str, Any]]:
        return cast(
            "list[dict[str, Any]]",
            self._template_service.list_by_type(template_type, active_only=active_only),
        )

    def get_default_for_type(self, template_type: str) -> dict[str, Any] | None:
        return cast(
            "dict[str, Any] | None",
            self._template_service.get_default_for_type(template_type),
        )

    def save_template_file(
        self, source_name: str, target_name: str, overwrite: bool = False
    ) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self._template_service.save_template_file(source_name, target_name, overwrite),
        )

    def save_template(self, template_data: dict[str, Any]) -> dict[str, Any]:
        """
        保存模板用例

        Args:
            template_data: 模板数据

        Returns:
            保存结果
        """
        return cast("dict[str, Any]", self._template_service.save_template(template_data))

    def update_template(self, template_id: int, template_data: dict[str, Any]) -> dict[str, Any]:
        """
        更新模板用例

        Args:
            template_id: 模板 ID
            template_data: 模板数据

        Returns:
            更新结果
        """
        return cast(
            "dict[str, Any]", self._template_service.update_template(template_id, template_data)
        )

    def delete_template(self, template_id: int) -> dict[str, Any]:
        """
        删除模板用例

        Args:
            template_id: 模板 ID

        Returns:
            删除结果
        """
        return cast("dict[str, Any]", self._template_service.delete_template(template_id))

    def decompose_template(
        self, file_path: str, template_type: str | None = None
    ) -> dict[str, Any]:
        """
        分解模板用例

        Args:
            file_path: 模板文件路径
            template_type: 模板类型

        Returns:
            分解结果
        """
        return cast(
            "dict[str, Any]", self._template_service.decompose_template(file_path, template_type)
        )


from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

instrument_application_service_class(TemplateApplicationService)


def get_template_app_service() -> TemplateApplicationService:
    """获取模板应用服务单例 (别名)"""
    return get_template_application_service()


def get_template_application_service() -> TemplateApplicationService:
    """获取模板应用服务单例"""
    return get_service_registry().template_application_service


def init_template_app_service(
    template_service=None,
) -> TemplateApplicationService:
    """初始化模板应用服务 (用于依赖注入) (别名)"""
    return init_template_application_service(template_service)


def init_template_application_service(
    template_service=None,
) -> TemplateApplicationService:
    """初始化模板应用服务 (用于依赖注入)"""
    service = TemplateApplicationService(template_service=template_service)
    get_service_registry().set_template_application_service(service)
    return service
