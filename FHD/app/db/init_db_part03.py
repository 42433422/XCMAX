# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib
from sqlalchemy.engine import Engine

def _facade():
    return importlib.import_module('app.db.init_db')

def ensure_sessions_market_refresh_token_column(engine: Engine | None=None, *, database_url: str | None=None) -> None:
    """补齐 ``sessions.market_refresh_token``（与 Alembic ``2026_05_22_sessions_market_refresh_token`` 一致）。"""
    from sqlalchemy import inspect, text
    real_engine: Engine | None = None
    url = (database_url or '').strip()
    if url:
        try:
            from app.db import _create_engine_for_url
            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning('无法按 DATABASE_URL 创建引擎以补齐 sessions.market_refresh_token: %s', exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine
            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
            return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if 'sessions' not in tables:
            return
        cols = {c['name'] for c in insp.get_columns('sessions')}
        if 'market_refresh_token' in cols:
            return
        _facade().logger.info('sessions 缺少 market_refresh_token 列，正在补齐 …')
        with real_engine.begin() as conn:
            if real_engine.dialect.name == 'postgresql':
                conn.execute(text('ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_refresh_token TEXT'))
            else:
                conn.execute(text('ALTER TABLE sessions ADD COLUMN market_refresh_token TEXT'))
        _facade().logger.info('sessions.market_refresh_token 已补齐')
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('sessions.market_refresh_token 兼容补列失败（可在仓库根执行 alembic upgrade head）：%s', exc)

def ensure_sessions_enterprise_entitlement_columns(engine: Engine | None=None, *, database_url: str | None=None) -> None:
    """补齐 ``sessions.market_user_id`` / ``entitled_mod_ids_json``（企业版 Mod 隔离缓存）。"""
    from sqlalchemy import inspect, text
    real_engine: Engine | None = None
    url = (database_url or '').strip()
    if url:
        try:
            from app.db import _create_engine_for_url
            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning('无法按 DATABASE_URL 创建引擎以补齐 sessions 企业权益列: %s', exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine
            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
            return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if 'sessions' not in tables:
            return
        cols = {c['name'] for c in insp.get_columns('sessions')}
        dialect = real_engine.dialect.name
        with real_engine.begin() as conn:
            if 'market_user_id' not in cols:
                _facade().logger.info('sessions 缺少 market_user_id 列，正在补齐 …')
                if dialect == 'postgresql':
                    conn.execute(text('ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_user_id INTEGER'))
                else:
                    conn.execute(text('ALTER TABLE sessions ADD COLUMN market_user_id INTEGER'))
            if 'entitled_mod_ids_json' not in cols:
                _facade().logger.info('sessions 缺少 entitled_mod_ids_json 列，正在补齐 …')
                if dialect == 'postgresql':
                    conn.execute(text('ALTER TABLE sessions ADD COLUMN IF NOT EXISTS entitled_mod_ids_json TEXT'))
                else:
                    conn.execute(text('ALTER TABLE sessions ADD COLUMN entitled_mod_ids_json TEXT'))
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('sessions 企业权益列兼容补列失败（可执行 alembic upgrade head）：%s', exc)

def ensure_sessions_account_meta_columns(engine: Engine | None=None, *, database_url: str | None=None) -> None:
    """补齐 sessions 账号类型 / 企业品牌 / 代管列。"""
    from sqlalchemy import inspect, text
    real_engine: Engine | None = None
    url = (database_url or '').strip()
    if url:
        try:
            from app.db import _create_engine_for_url
            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning('无法创建引擎以补齐 sessions 账号元数据列: %s', exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine
            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
            return
    additions = [('account_kind', 'VARCHAR(32)', "'enterprise'"), ('company_brand', 'VARCHAR(256)', "''"), ('market_is_admin', 'BOOLEAN', 'FALSE'), ('market_is_enterprise', 'BOOLEAN', 'FALSE'), ('impersonating_market_user_id', 'INTEGER', None), ('impersonating_username', 'VARCHAR(128)', "''"), ('tenant_id', 'INTEGER', None), ('market_membership_tier', 'VARCHAR(32)', None)]
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if 'sessions' not in tables:
            return
        cols = {c['name'] for c in insp.get_columns('sessions')}
        dialect = real_engine.dialect.name
        with real_engine.begin() as conn:
            for (name, col_type, default_sql) in additions:
                if name in cols:
                    continue
                _facade().logger.info('sessions 缺少 %s 列，正在补齐 …', name)
                if dialect == 'postgresql':
                    default_clause = f' DEFAULT {default_sql}' if default_sql else ''
                    conn.execute(text(f'ALTER TABLE sessions ADD COLUMN IF NOT EXISTS {name} {col_type}{default_clause}'))
                else:
                    default_clause = f' DEFAULT {default_sql}' if default_sql else ''
                    conn.execute(text(f'ALTER TABLE sessions ADD COLUMN {name} {col_type}{default_clause}'))
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('sessions 账号元数据列兼容补列失败: %s', exc)

def ensure_users_tenant_id_column(engine: Engine | None=None, *, database_url: str | None=None) -> None:
    """补齐 ``users.tenant_id``，避免旧桌面 SQLite 企业登录时查询 User 失败。"""
    from sqlalchemy import inspect, text
    real_engine: Engine | None = None
    url = (database_url or '').strip()
    if url:
        try:
            from app.db import _create_engine_for_url
            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning('无法创建引擎以补齐 users.tenant_id: %s', exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine
            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
            return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if 'users' not in tables:
            return
        cols = {c['name'] for c in insp.get_columns('users')}
        if 'tenant_id' in cols:
            return
        _facade().logger.info('users 缺少 tenant_id 列，正在补齐 …')
        with real_engine.begin() as conn:
            if real_engine.dialect.name == 'postgresql':
                conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id INTEGER'))
            else:
                conn.execute(text('ALTER TABLE users ADD COLUMN tenant_id INTEGER'))
        _facade().logger.info('users.tenant_id 已补齐')
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('users.tenant_id 兼容补列失败: %s', exc)

def ensure_business_tenant_id_columns(engine: Engine | None=None, *, database_url: str | None=None) -> None:
    """为业务表补齐 ``tenant_id`` 列（多租户数据隔离作用域；nullable）。"""
    from sqlalchemy import inspect, text
    real_engine: Engine | None = None
    url = (database_url or '').strip()
    if url:
        try:
            from app.db import _create_engine_for_url
            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning('无法创建引擎以补齐业务表 tenant_id: %s', exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine
            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
            return
    business_tables = ('products', 'customers', 'purchase_units', 'materials', 'shipment_records', 'financial_transactions', 'suppliers', 'purchase_orders', 'purchase_order_items', 'purchase_inbounds', 'purchase_inbound_items', 'warehouses', 'storage_locations', 'inventory_ledger', 'inventory_transactions', 'templates')
    try:
        insp = inspect(real_engine)
        existing = set(insp.get_table_names() or [])
        dialect = real_engine.dialect.name
        with real_engine.begin() as conn:
            for table in business_tables:
                if table not in existing:
                    continue
                cols = {c['name'] for c in insp.get_columns(table)}
                if 'tenant_id' in cols:
                    continue
                _facade().logger.info('%s 缺少 tenant_id 列，正在补齐 …', table)
                if dialect == 'postgresql':
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id INTEGER'))
                else:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN tenant_id INTEGER'))
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('业务表 tenant_id 兼容补列失败: %s', exc)

def ensure_user_profile_columns(engine: Engine | None=None, *, database_url: str | None=None) -> None:
    """补齐 ``users.tier`` / ``users.industry_id``，管理端用户等级与行业编辑依赖。"""
    from sqlalchemy import inspect, text
    real_engine: Engine | None = None
    url = (database_url or '').strip()
    if url:
        try:
            from app.db import _create_engine_for_url
            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning('无法创建引擎以补齐 users.tier/industry_id: %s', exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine
            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
            return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if 'users' not in tables:
            return
        cols = {c['name'] for c in insp.get_columns('users')}
        dialect = real_engine.dialect.name
        json_type = 'JSONB' if dialect == 'postgresql' else 'TEXT'
        additions = [('tier', 'VARCHAR(32)', "'personal'"), ('industry_id', 'VARCHAR(32)', "'通用'"), ('account_tier', 'VARCHAR(32)', None), ('budget_range', 'VARCHAR(32)', None), ('entitled_industries', json_type, None), ('failed_login_attempts', 'INTEGER', '0'), ('locked_until', 'TIMESTAMP', None), ('email_verified', 'BOOLEAN', 'FALSE')]
        with real_engine.begin() as conn:
            for (name, col_type, default_sql) in additions:
                if name in cols:
                    continue
                _facade().logger.info('users 缺少 %s 列，正在补齐 …', name)
                default_clause = f' DEFAULT {default_sql}' if default_sql else ''
                if dialect == 'postgresql':
                    conn.execute(text(f'ALTER TABLE users ADD COLUMN IF NOT EXISTS {name} {col_type}{default_clause}'))
                else:
                    conn.execute(text(f'ALTER TABLE users ADD COLUMN {name} {col_type}{default_clause}'))
        _facade().logger.info('users 账号/行业列已补齐')
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('users 账号/行业列兼容补列失败: %s', exc)

def init_im_tables(engine: Engine | None=None, *, database_url: str | None=None) -> None:
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
    from app.db.models.im import ImConversation, ImConversationMember, ImMessage
    target_tables = [_facade()._orm_table(ImConversation), _facade()._orm_table(ImConversationMember), _facade()._orm_table(ImMessage), _facade()._orm_table(AiEmployeeProfile)]
    Base.metadata.create_all(engine, tables=target_tables, checkfirst=True)

def init_approval_tables(engine: Engine) -> None:
    """
    在主库上创建审批流相关表（approval_flows / approval_flow_nodes /
    approval_requests / approval_records / approval_delegations）。

    与 Alembic `xcagi_v5_approval_system` 对齐；启动时幂等补齐，便于未跑迁移的环境。
    同时确保 `approval_flows.business_type` 列存在（旧库可能缺失）。
    """
    from sqlalchemy import inspect, text
    from app.db.base import Base
    from app.db.models.approval import ApprovalDelegation, ApprovalFlow, ApprovalFlowNode, ApprovalRecord, ApprovalRequest
    target_tables = [_facade()._orm_table(ApprovalFlow), _facade()._orm_table(ApprovalFlowNode), _facade()._orm_table(ApprovalRequest), _facade()._orm_table(ApprovalRecord), _facade()._orm_table(ApprovalDelegation)]
    real_engine = engine
    try:
        from app.db import _get_engine as _get_real_engine
        real_engine = _get_real_engine()
    except _facade().RECOVERABLE_ERRORS:
        pass
    try:
        Base.metadata.create_all(real_engine, tables=target_tables, checkfirst=True)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('approval 表 create_all 失败（继续尝试 ALTER 兼容）：%s', exc)
    try:
        insp = inspect(real_engine)
        if 'approval_flows' in set(insp.get_table_names() or []):
            cols = {c['name'] for c in insp.get_columns('approval_flows')}
            if 'business_type' not in cols:
                _facade().logger.info('approval_flows 缺少 business_type 列，开始补列 …')
                with real_engine.begin() as conn:
                    if real_engine.dialect.name == 'postgresql':
                        conn.execute(text("ALTER TABLE approval_flows ADD COLUMN IF NOT EXISTS business_type VARCHAR(64) DEFAULT 'general'"))
                        conn.execute(text('CREATE INDEX IF NOT EXISTS ix_approval_flows_business_type ON approval_flows (business_type)'))
                    else:
                        conn.execute(text("ALTER TABLE approval_flows ADD COLUMN business_type VARCHAR(64) DEFAULT 'general'"))
                _facade().logger.info('approval_flows.business_type 已补齐')
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('approval_flows.business_type 兼容补列失败: %s', exc)

def ensure_product_query_indexes(engine: Engine) -> None:
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
    if 'products' not in names:
        return
    stmts = ['CREATE INDEX IF NOT EXISTS ix_products_unit ON products (unit)', 'CREATE INDEX IF NOT EXISTS ix_products_model_number ON products (model_number)']
    with engine.begin() as conn:
        for sql in stmts:
            try:
                conn.execute(text(sql))
            except _facade().RECOVERABLE_ERRORS as e:
                _facade().logger.debug('创建 products 索引跳过: %s | %s', sql, e)

def init_service_bridge_tables(engine: Engine) -> None:
    """在主库创建客服桥接表（service_requests / service_bridge_config）。"""
    from app.db.base import Base
    from app.db.models.service_request import ServiceBridgeConfig, ServiceRequest
    target_tables = [_facade()._orm_table(ServiceRequest), _facade()._orm_table(ServiceBridgeConfig)]
    real_engine = engine
    try:
        from app.db import _get_engine as _get_real_engine
        real_engine = _get_real_engine()
    except _facade().RECOVERABLE_ERRORS:
        pass
    try:
        Base.metadata.create_all(real_engine, tables=target_tables, checkfirst=True)
        _facade().logger.info('service_bridge 表已就绪')
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('service_bridge 表 create_all 失败: %s', exc)

def init_persona_tables(engine: Engine) -> None:
    """在主库创建 persona 画像表（persona_profile / persona_event_log）。

    注：本仓库 alembic 链在普通启动时不触发（建表统一走 init_db + lifespan），
    故 persona 两张表必须在此显式 create_all，否则 PersonaRepositoryImpl 落盘会失败。
    """
    from app.db.base import Base
    from app.infrastructure.persona.models import PersonaEventLogModel, PersonaProfileModel
    target_tables = [_facade()._orm_table(PersonaProfileModel), _facade()._orm_table(PersonaEventLogModel)]
    real_engine = engine
    try:
        from app.db import _get_engine as _get_real_engine
        real_engine = _get_real_engine()
    except _facade().RECOVERABLE_ERRORS:
        pass
    try:
        Base.metadata.create_all(real_engine, tables=target_tables, checkfirst=True)
        _facade().logger.info('persona 表已就绪')
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('persona 表 create_all 失败: %s', exc)
