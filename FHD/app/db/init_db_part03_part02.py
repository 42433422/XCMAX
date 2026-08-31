# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.db.init_db")


def ensure_im_customer_service_columns(engine: _facade().Engine) -> None:
    """幂等补齐企业客服消息来源列，兼容未接入 Alembic 的生产库。"""
    from sqlalchemy import inspect, text

    try:
        insp = inspect(engine)
        if "im_messages" not in set(insp.get_table_names() or []):
            return
        columns = {str(row.get("name") or "") for row in insp.get_columns("im_messages")}
        dialect = engine.dialect.name
        with engine.begin() as conn:
            if "origin" not in columns:
                _facade().logger.info("im_messages 缺少 origin 列，正在补齐 …")
                if dialect == "postgresql":
                    conn.execute(
                        text(
                            "ALTER TABLE im_messages ADD COLUMN IF NOT EXISTS "
                            "origin VARCHAR(32) NOT NULL DEFAULT 'user'"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE im_messages ADD COLUMN "
                            "origin VARCHAR(32) NOT NULL DEFAULT 'user'"
                        )
                    )
            if "operator_user_id" not in columns:
                _facade().logger.info("im_messages 缺少 operator_user_id 列，正在补齐 …")
                if dialect == "postgresql":
                    conn.execute(
                        text(
                            "ALTER TABLE im_messages ADD COLUMN IF NOT EXISTS "
                            "operator_user_id INTEGER"
                        )
                    )
                else:
                    conn.execute(
                        text("ALTER TABLE im_messages ADD COLUMN operator_user_id INTEGER")
                    )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_im_messages_operator_user_id "
                    "ON im_messages (operator_user_id)"
                )
            )
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning(
            "企业客服消息来源列兼容补齐失败（可执行对应 Alembic 迁移）：%s", exc
        )


def init_im_tables(
    engine: _facade().Engine | None = None, *, database_url: str | None = None
) -> None:
    """在主库上创建企业内部 IM V0 表 + AI 员工档案表。

    IM 发消息时会按 peer 反查 ``ai_employee_profiles``；缺表会在 SQLite
    测试/桌面引导下直接 500，因此与三张 IM 表一并幂等创建。
    """
    if engine is None:
        if database_url:
            from app.db import _create_engine_for_url

            engine = _create_engine_for_url(database_url)
        else:
            from app.db import _get_engine

            engine = _get_engine()
    from app.db.base import Base
    from app.db.models.ai_employee import AiEmployeeProfile
    from app.db.models.im import (
        ImConversation,
        ImConversationMember,
        ImCustomerServiceAutomationState,
        ImMessage,
    )

    target_tables = [
        _facade()._orm_table(ImConversation),
        _facade()._orm_table(ImConversationMember),
        _facade()._orm_table(ImMessage),
        _facade()._orm_table(ImCustomerServiceAutomationState),
        _facade()._orm_table(AiEmployeeProfile),
    ]
    Base.metadata.create_all(engine, tables=target_tables, checkfirst=True)
    ensure_im_customer_service_columns(engine)


def init_approval_tables(engine: _facade().Engine) -> None:
    """
    在主库上创建审批流相关表（approval_flows / approval_flow_nodes /
    approval_requests / approval_records / approval_delegations）。

    与 Alembic `xcagi_v5_approval_system` 对齐；启动时幂等补齐，便于未跑迁移的环境。
    同时确保 `approval_flows.business_type` 列存在（旧库可能缺失）。
    """
    from sqlalchemy import inspect, text

    from app.db.base import Base
    from app.db.models.approval import (
        ApprovalDelegation,
        ApprovalFlow,
        ApprovalFlowNode,
        ApprovalRecord,
        ApprovalRequest,
    )

    target_tables = [
        _facade()._orm_table(ApprovalFlow),
        _facade()._orm_table(ApprovalFlowNode),
        _facade()._orm_table(ApprovalRequest),
        _facade()._orm_table(ApprovalRecord),
        _facade()._orm_table(ApprovalDelegation),
    ]
    real_engine = engine
    try:
        from app.db import _get_engine as _get_real_engine

        real_engine = _get_real_engine()
    except _facade().RECOVERABLE_ERRORS:
        pass
    try:
        Base.metadata.create_all(real_engine, tables=target_tables, checkfirst=True)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("approval 表 create_all 失败（继续尝试 ALTER 兼容）：%s", exc)
    try:
        insp = inspect(real_engine)
        if "approval_flows" in set(insp.get_table_names() or []):
            cols = {c["name"] for c in insp.get_columns("approval_flows")}
            if "business_type" not in cols:
                _facade().logger.info("approval_flows 缺少 business_type 列，开始补列 …")
                with real_engine.begin() as conn:
                    if real_engine.dialect.name == "postgresql":
                        conn.execute(
                            text(
                                "ALTER TABLE approval_flows ADD COLUMN IF NOT EXISTS business_type VARCHAR(64) DEFAULT 'general'"
                            )
                        )
                        conn.execute(
                            text(
                                "CREATE INDEX IF NOT EXISTS ix_approval_flows_business_type ON approval_flows (business_type)"
                            )
                        )
                    else:
                        conn.execute(
                            text(
                                "ALTER TABLE approval_flows ADD COLUMN business_type VARCHAR(64) DEFAULT 'general'"
                            )
                        )
                _facade().logger.info("approval_flows.business_type 已补齐")
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("approval_flows.business_type 兼容补列失败: %s", exc)


def ensure_product_query_indexes(engine: _facade().Engine) -> None:
    """
    为 products 表补齐常用查询索引（按客户 unit、型号 model_number），
    便于列表筛选与 AI 工具链查库；对已存在库使用 IF NOT EXISTS 幂等。
    """
    from sqlalchemy import inspect, text

    try:
        insp = inspect(engine)
        names = set(insp.get_table_names() or [])
    except _facade().RECOVERABLE_ERRORS:
        names = set()
    if "products" not in names:
        return
    stmts = [
        "CREATE INDEX IF NOT EXISTS ix_products_unit ON products (unit)",
        "CREATE INDEX IF NOT EXISTS ix_products_model_number ON products (model_number)",
    ]
    with engine.begin() as conn:
        for sql in stmts:
            try:
                conn.execute(text(sql))
            except _facade().RECOVERABLE_ERRORS as e:
                _facade().logger.debug("创建 products 索引跳过: %s | %s", sql, e)


def init_service_bridge_tables(engine: _facade().Engine) -> None:
    """在主库创建客服桥接表（service_requests / service_bridge_config）。"""
    from app.db.base import Base
    from app.db.models.service_request import ServiceBridgeConfig, ServiceRequest

    target_tables = [
        _facade()._orm_table(ServiceRequest),
        _facade()._orm_table(ServiceBridgeConfig),
    ]
    real_engine = engine
    try:
        from app.db import _get_engine as _get_real_engine

        real_engine = _get_real_engine()
    except _facade().RECOVERABLE_ERRORS:
        pass
    try:
        Base.metadata.create_all(real_engine, tables=target_tables, checkfirst=True)
        _facade().logger.info("service_bridge 表已就绪")
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("service_bridge 表 create_all 失败: %s", exc)


def init_persona_tables(engine: _facade().Engine) -> None:
    """在主库创建 persona 画像表（persona_profile / persona_event_log）。

    注：本仓库 alembic 链在普通启动时不触发（建表统一走 init_db + lifespan），
    故 persona 两张表必须在此显式 create_all，否则 PersonaRepositoryImpl 落盘会失败。
    """
    from app.db.base import Base
    from app.infrastructure.persona.models import (
        PersonaEventLogModel,
        PersonaProfileModel,
    )

    target_tables = [
        _facade()._orm_table(PersonaProfileModel),
        _facade()._orm_table(PersonaEventLogModel),
    ]
    real_engine = engine
    try:
        from app.db import _get_engine as _get_real_engine

        real_engine = _get_real_engine()
    except _facade().RECOVERABLE_ERRORS:
        pass
    try:
        Base.metadata.create_all(real_engine, tables=target_tables, checkfirst=True)
        _facade().logger.info("persona 表已就绪")
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("persona 表 create_all 失败: %s", exc)
