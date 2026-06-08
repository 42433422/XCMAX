"""新增业务表：脚本工作流、知识库、事件投递、作者收益、开票等。

Revision ID: 20260505_new_tables
Revises: 20260502_money
Create Date: 2026-05-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "20260505_new_tables"
down_revision = "20260502_money"
branch_labels = None
depends_on = None

# 需要创建的新表（若已存在则跳过）
_NEW_TABLES_SQL = [
    # ESkill
    """
    CREATE TABLE IF NOT EXISTS eskills (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        name VARCHAR(256) NOT NULL,
        description TEXT DEFAULT '',
        script_text TEXT DEFAULT '',
        schema_in_json TEXT DEFAULT '{}',
        schema_out_json TEXT DEFAULT '{}',
        status VARCHAR(32) DEFAULT 'draft',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_eskills_user_id ON eskills(user_id)""",
    """
    CREATE TABLE IF NOT EXISTS eskill_versions (
        id SERIAL PRIMARY KEY,
        eskill_id INTEGER NOT NULL REFERENCES eskills(id),
        version_tag VARCHAR(64) DEFAULT '',
        script_text TEXT DEFAULT '',
        schema_in_json TEXT DEFAULT '{}',
        schema_out_json TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_eskill_versions_eskill_id ON eskill_versions(eskill_id)""",
    """
    CREATE TABLE IF NOT EXISTS eskill_runs (
        id SERIAL PRIMARY KEY,
        eskill_id INTEGER NOT NULL REFERENCES eskills(id),
        user_id INTEGER REFERENCES users(id),
        status VARCHAR(32) DEFAULT 'pending',
        input_json TEXT DEFAULT '{}',
        output_json TEXT DEFAULT '{}',
        error TEXT DEFAULT '',
        duration_ms FLOAT DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_eskill_runs_eskill_id ON eskill_runs(eskill_id)""",
    # 配额与权益
    """
    CREATE TABLE IF NOT EXISTS quotas (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        plan_id VARCHAR(64) DEFAULT '',
        quota_type VARCHAR(64) NOT NULL,
        total INTEGER DEFAULT 0,
        used INTEGER DEFAULT 0,
        reset_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_quotas_user_id ON quotas(user_id)""",
    """
    CREATE TABLE IF NOT EXISTS entitlements (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        feature VARCHAR(128) NOT NULL,
        granted_by VARCHAR(64) DEFAULT '',
        expires_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_entitlements_user_id ON entitlements(user_id)""",
    # 员工执行指标
    """
    CREATE TABLE IF NOT EXISTS employee_execution_metrics (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        employee_id VARCHAR(128) NOT NULL,
        task VARCHAR(128) DEFAULT '',
        status VARCHAR(32) DEFAULT 'success',
        duration_ms FLOAT DEFAULT 0.0,
        llm_tokens INTEGER DEFAULT 0,
        error TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_employee_execution_metrics_user_id ON employee_execution_metrics(user_id)""",
    """CREATE INDEX IF NOT EXISTS ix_employee_execution_metrics_employee_id ON employee_execution_metrics(employee_id)""",
    # 工作流触发器
    """
    CREATE TABLE IF NOT EXISTS workflow_triggers (
        id SERIAL PRIMARY KEY,
        workflow_id INTEGER NOT NULL REFERENCES workflows(id),
        trigger_type VARCHAR(64) NOT NULL,
        config_json TEXT DEFAULT '{}',
        trigger_key VARCHAR(128) DEFAULT '',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_workflow_triggers_workflow_id ON workflow_triggers(workflow_id)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS ix_workflow_triggers_trigger_key ON workflow_triggers(trigger_key)""",
    # 工作流版本
    """
    CREATE TABLE IF NOT EXISTS workflow_versions (
        id SERIAL PRIMARY KEY,
        workflow_id INTEGER NOT NULL REFERENCES workflows(id),
        version_tag VARCHAR(64) DEFAULT '',
        snapshot_json TEXT DEFAULT '{}',
        published_by INTEGER REFERENCES users(id),
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_workflow_versions_workflow_id ON workflow_versions(workflow_id)""",
    # Webhook 订阅与投递
    """
    CREATE TABLE IF NOT EXISTS webhook_subscriptions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        url TEXT NOT NULL,
        event_types TEXT DEFAULT '[]',
        secret VARCHAR(256) DEFAULT '',
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_webhook_subscriptions_user_id ON webhook_subscriptions(user_id)""",
    """
    CREATE TABLE IF NOT EXISTS webhook_deliveries (
        id SERIAL PRIMARY KEY,
        subscription_id INTEGER NOT NULL REFERENCES webhook_subscriptions(id),
        event_type VARCHAR(128) NOT NULL,
        payload_json TEXT DEFAULT '{}',
        status VARCHAR(32) DEFAULT 'pending',
        response_status INTEGER,
        response_body TEXT DEFAULT '',
        attempt_count INTEGER DEFAULT 0,
        next_retry_at TIMESTAMP,
        delivered_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_subscription_id ON webhook_deliveries(subscription_id)""",
    # 开发者令牌
    """
    CREATE TABLE IF NOT EXISTS developer_tokens (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        name VARCHAR(128) NOT NULL,
        token_hash VARCHAR(256) NOT NULL,
        scopes TEXT DEFAULT '[]',
        last_used_at TIMESTAMP,
        expires_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_developer_tokens_user_id ON developer_tokens(user_id)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS ix_developer_tokens_token_hash ON developer_tokens(token_hash)""",
    """
    CREATE TABLE IF NOT EXISTS developer_key_export_events (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        provider VARCHAR(64) NOT NULL,
        export_reason TEXT DEFAULT '',
        ip_address VARCHAR(64) DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_developer_key_export_events_user_id ON developer_key_export_events(user_id)""",
    # 通知
    """
    CREATE TABLE IF NOT EXISTS notifications (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        type VARCHAR(64) NOT NULL,
        title VARCHAR(256) DEFAULT '',
        body TEXT DEFAULT '',
        meta_json TEXT DEFAULT '{}',
        is_read BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications(user_id)""",
    # 退款申请（若不存在）
    """
    CREATE TABLE IF NOT EXISTS refund_requests (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        order_no VARCHAR(128) DEFAULT '',
        amount NUMERIC(12,2) DEFAULT 0,
        reason TEXT DEFAULT '',
        status VARCHAR(32) DEFAULT 'pending',
        admin_note TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_refund_requests_user_id ON refund_requests(user_id)""",
    # AI 模型价格与能力
    """
    CREATE TABLE IF NOT EXISTS ai_model_prices (
        id SERIAL PRIMARY KEY,
        provider VARCHAR(64) NOT NULL,
        model_id VARCHAR(128) NOT NULL,
        input_price_per_1k NUMERIC(12,6) DEFAULT 0,
        output_price_per_1k NUMERIC(12,6) DEFAULT 0,
        min_charge NUMERIC(12,2) DEFAULT 0,
        currency VARCHAR(8) DEFAULT 'CNY',
        is_active BOOLEAN DEFAULT TRUE,
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE UNIQUE INDEX IF NOT EXISTS ix_ai_model_prices_provider_model ON ai_model_prices(provider, model_id)""",
    """
    CREATE TABLE IF NOT EXISTS llm_model_capabilities (
        id SERIAL PRIMARY KEY,
        provider VARCHAR(64) NOT NULL,
        model_id VARCHAR(128) NOT NULL,
        context_window INTEGER DEFAULT 0,
        supports_vision BOOLEAN DEFAULT FALSE,
        supports_function_call BOOLEAN DEFAULT FALSE,
        supports_streaming BOOLEAN DEFAULT TRUE,
        max_output_tokens INTEGER DEFAULT 0,
        meta_json TEXT DEFAULT '{}',
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    # 知识库
    """
    CREATE TABLE IF NOT EXISTS knowledge_collections (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        name VARCHAR(256) NOT NULL,
        description TEXT DEFAULT '',
        embedding_provider VARCHAR(64) DEFAULT '',
        embedding_source VARCHAR(64) DEFAULT '',
        is_public BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_knowledge_collections_user_id ON knowledge_collections(user_id)""",
    """
    CREATE TABLE IF NOT EXISTS knowledge_memberships (
        id SERIAL PRIMARY KEY,
        collection_id INTEGER NOT NULL REFERENCES knowledge_collections(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        role VARCHAR(32) DEFAULT 'viewer',
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_knowledge_memberships_collection_id ON knowledge_memberships(collection_id)""",
    """
    CREATE TABLE IF NOT EXISTS knowledge_documents (
        id SERIAL PRIMARY KEY,
        collection_id INTEGER NOT NULL REFERENCES knowledge_collections(id),
        filename VARCHAR(512) DEFAULT '',
        content_type VARCHAR(128) DEFAULT '',
        text_content TEXT DEFAULT '',
        embedding_json TEXT DEFAULT '',
        status VARCHAR(32) DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_knowledge_documents_collection_id ON knowledge_documents(collection_id)""",
    # 风险事件
    """
    CREATE TABLE IF NOT EXISTS risk_events (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id),
        event_type VARCHAR(64) NOT NULL,
        severity VARCHAR(16) DEFAULT 'low',
        detail_json TEXT DEFAULT '{}',
        ip_address VARCHAR(64) DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_risk_events_user_id ON risk_events(user_id)""",
    # 事件投递箱（发件箱模式）
    """
    CREATE TABLE IF NOT EXISTS event_outbox (
        id SERIAL PRIMARY KEY,
        event_type VARCHAR(128) NOT NULL,
        aggregate_id VARCHAR(128) DEFAULT '',
        payload_json TEXT DEFAULT '{}',
        status VARCHAR(32) DEFAULT 'pending',
        attempts INTEGER DEFAULT 0,
        last_error TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW(),
        processed_at TIMESTAMP
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_event_outbox_status ON event_outbox(status)""",
    """
    CREATE TABLE IF NOT EXISTS event_outbox_dlq (
        id SERIAL PRIMARY KEY,
        original_id INTEGER,
        event_type VARCHAR(128) NOT NULL,
        payload_json TEXT DEFAULT '{}',
        error TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    # 脚本工作流
    """
    CREATE TABLE IF NOT EXISTS script_workflows (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        name VARCHAR(256) NOT NULL,
        brief_json TEXT DEFAULT '{}',
        script_text TEXT DEFAULT '',
        schema_in_json TEXT DEFAULT '{}',
        status VARCHAR(32) DEFAULT 'draft',
        agent_session_id VARCHAR(64) DEFAULT '',
        migrated_from_workflow_id INTEGER,
        last_manual_sandbox_run_id INTEGER,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_script_workflows_user_id ON script_workflows(user_id)""",
    """CREATE INDEX IF NOT EXISTS ix_script_workflows_status ON script_workflows(status)""",
    """
    CREATE TABLE IF NOT EXISTS script_workflow_versions (
        id SERIAL PRIMARY KEY,
        workflow_id INTEGER NOT NULL REFERENCES script_workflows(id),
        version_tag VARCHAR(64) DEFAULT '',
        script_text TEXT DEFAULT '',
        schema_in_json TEXT DEFAULT '{}',
        brief_json TEXT DEFAULT '{}',
        published_by INTEGER REFERENCES users(id),
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_script_workflow_versions_workflow_id ON script_workflow_versions(workflow_id)""",
    """
    CREATE TABLE IF NOT EXISTS script_workflow_runs (
        id SERIAL PRIMARY KEY,
        workflow_id INTEGER NOT NULL REFERENCES script_workflows(id),
        user_id INTEGER REFERENCES users(id),
        status VARCHAR(32) DEFAULT 'pending',
        input_json TEXT DEFAULT '{}',
        output_json TEXT DEFAULT '{}',
        error TEXT DEFAULT '',
        duration_ms FLOAT DEFAULT 0.0,
        sandbox BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_script_workflow_runs_workflow_id ON script_workflow_runs(workflow_id)""",
    # 作者收益与开票
    """
    CREATE TABLE IF NOT EXISTS author_earnings (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        catalog_item_id INTEGER REFERENCES catalog_items(id),
        order_no VARCHAR(128) DEFAULT '',
        amount NUMERIC(12,2) DEFAULT 0,
        status VARCHAR(32) DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_author_earnings_user_id ON author_earnings(user_id)""",
    """
    CREATE TABLE IF NOT EXISTS author_withdrawals (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        amount NUMERIC(12,2) DEFAULT 0,
        method VARCHAR(64) DEFAULT '',
        account_info_json TEXT DEFAULT '{}',
        status VARCHAR(32) DEFAULT 'pending',
        admin_note TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW(),
        processed_at TIMESTAMP
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_author_withdrawals_user_id ON author_withdrawals(user_id)""",
    """
    CREATE TABLE IF NOT EXISTS invoices (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        order_no VARCHAR(128) DEFAULT '',
        amount NUMERIC(12,2) DEFAULT 0,
        type VARCHAR(32) DEFAULT 'vat_general',
        header TEXT DEFAULT '',
        tax_no VARCHAR(128) DEFAULT '',
        email VARCHAR(256) DEFAULT '',
        status VARCHAR(32) DEFAULT 'pending',
        admin_note TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW(),
        processed_at TIMESTAMP
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_invoices_user_id ON invoices(user_id)""",
    """
    CREATE TABLE IF NOT EXISTS reconciliation_reports (
        id SERIAL PRIMARY KEY,
        period_start TIMESTAMP NOT NULL,
        period_end TIMESTAMP NOT NULL,
        status VARCHAR(32) DEFAULT 'pending',
        summary_json TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for sql in _NEW_TABLES_SQL:
        sql = sql.strip()
        if sql:
            op.execute(sa.text(sql))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # 按依赖倒序删除
    _drop_order = [
        "reconciliation_reports", "invoices", "author_withdrawals", "author_earnings",
        "script_workflow_runs", "script_workflow_versions", "script_workflows",
        "event_outbox_dlq", "event_outbox",
        "risk_events",
        "knowledge_documents", "knowledge_memberships", "knowledge_collections",
        "llm_model_capabilities", "ai_model_prices",
        "refund_requests",
        "notifications",
        "developer_key_export_events", "developer_tokens",
        "webhook_deliveries", "webhook_subscriptions",
        "workflow_versions", "workflow_triggers",
        "employee_execution_metrics",
        "entitlements", "quotas",
        "eskill_runs", "eskill_versions", "eskills",
    ]
    for table in _drop_order:
        op.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))
