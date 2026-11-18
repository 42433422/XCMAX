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


def _positive_runtime_id(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def clear_document_templates(runtime_context: dict) -> tuple[dict, int]:
    """清空模板库；工具 worker 没有请求态，必须用运行时上下文显式绑定租户与账号。"""
    from app.application import get_template_app_service
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
    from app.infrastructure.tenant_scope import owned_tenant_id, owned_tenant_scope
    from app.legacy.routes.document_templates_compat import run_archive_template_delete

    tenant_id = _positive_runtime_id(runtime_context.get("tenant_id"))
    owner_id = _positive_runtime_id(runtime_context.get("user_id"))
    denied = {
        "success": False,
        "error_code": "template_scope_required",
        "message": "清理模板需要当前账号与租户的有效身份授权",
    }
    if tenant_id is None or owner_id is None:
        return denied, 403
    try:
        actor = _bound_actor(runtime_context)
        if actor.id != owner_id or owned_tenant_id() not in (None, tenant_id):
            return denied, 403
    except AgentModAuthorizationError:
        return denied, 403
    service = get_template_app_service()
    deleted = skipped = 0
    base_dir = str(runtime_context.get("template_base_dir") or "") or None
    starter_ids: list[str] = []
    builtin_paths: list[str] = []
    with owned_tenant_scope(tenant_id):
        listed = service.get_templates(tenant_id=tenant_id) or {}
        rows = listed.get("templates") if isinstance(listed, dict) else None
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            template_id = str(item.get("id") or "").strip()
            if not template_id:
                continue
            if template_id.startswith("seed:"):
                starter_ids.append(template_id)
                continue
            if not (
                template_id.startswith("fs:")
                or template_id.startswith("db:")
                or template_id.isdigit()
            ):
                skipped += 1
                continue
            item_data, item_status = run_archive_template_delete(
                {"id": template_id}, base_dir=base_dir
            )
            if item_status == 200 and item_data.get("success"):
                deleted += 1
                continue
            # 安装目录里的内置表格不能删字节；改为按租户隐藏，保证列表真的被清空。
            installed_path = str(item.get("path") or item.get("file_path") or "").strip()
            if item_status == 403 and installed_path:
                builtin_paths.append(installed_path)
                continue
            skipped += 1
        hidden = service.hide_templates(ids=starter_ids, paths=builtin_paths)
        # 模板库页面实际列出的是审阅归档（elt_archive_assets），只清 elt_templates
        # 会让「清理后页面仍满屏」；同一动作必须一并清掉当前账号的归档资产。
        deleted_archives = service.purge_archive_assets(tenant_id=tenant_id, owner_id=owner_id)
    if deleted or hidden or deleted_archives:
        message = f"已清理 {deleted} 个自定义模板，隐藏 {hidden} 个内置模板"
    elif skipped:
        message = f"模板库未能清理：{skipped} 个模板不支持删除"
    else:
        message = "模板库已经是空的"
    if deleted_archives:
        message += f"，同时清掉 {deleted_archives} 个已归档模板"
    if skipped and (deleted or hidden or deleted_archives):
        message += f"，{skipped} 个未能清理"
    return (
        {
            "success": not skipped or bool(deleted or hidden or deleted_archives),
            "message": message,
            "deleted_templates": deleted,
            "hidden_templates": hidden,
            "deleted_archives": deleted_archives,
            "skipped_templates": skipped,
        },
        200,
    )


def publish_document_template_change(action: str, result: dict) -> None:
    """通知已打开的模板库刷新；观测通道失败不能改变工具执行结果。"""
    from app.infrastructure.chat_stream_lifetime import publish_stream_tool_record
    from app.utils.operational_errors import BOUNDARY_ERRORS

    try:
        publish_stream_tool_record(
            {
                "node_id": f"document-template-{action or 'change'}",
                "tool_id": "document_template",
                "action": str(action or ""),
                "phase": "finished",
                "success": bool(result.get("success")),
                "output_preview": str(result.get("message") or "")[:200],
            }
        )
    except BOUNDARY_ERRORS:
        pass


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

    def purge_archive_assets(self, *, tenant_id: int, owner_id: int) -> int:
        """清理已授权账号的归档；身份必须显式传入，不能回退到其他请求。"""
        from app.db.models.elt_archive import EltArchiveAsset, EltArchiveVersion
        from app.db.session import get_db
        from app.infrastructure.tenant_scope import TenantScopeError, owned_tenant_id, tenant_scope

        tenant = _positive_runtime_id(tenant_id)
        owner = _positive_runtime_id(owner_id)
        if tenant is None or owner is None or owned_tenant_id() not in (None, tenant):
            raise TenantScopeError("清理归档缺少有效账号与租户")
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
                EltArchiveVersion.owner_user_id == owner,
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
