"""会员套餐、配额、开票与作者结算。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

from modstore_server.db.base import Base


class PlanTemplate(Base):
    __tablename__ = "plan_templates"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    price = Column(Numeric(12, 2), default=0.0)
    features_json = Column(Text, default="[]")
    quotas_json = Column(Text, default="{}")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class UserPlan(Base):
    __tablename__ = "user_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan_id = Column(String(64), ForeignKey("plan_templates.id"), nullable=False, index=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    auto_renew = Column(Boolean, default=True, nullable=False)
    renewal_fail_reason = Column(Text, default="")


class Quota(Base):
    __tablename__ = "quotas"
    __table_args__ = (UniqueConstraint("user_id", "quota_type", name="uq_user_quota_type"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    quota_type = Column(String(64), nullable=False, index=True)
    total = Column(Integer, default=0)
    used = Column(Integer, default=0)
    reset_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Entitlement(Base):
    __tablename__ = "entitlements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    catalog_id = Column(Integer, ForeignKey("catalog_items.id"), nullable=True, index=True)
    entitlement_type = Column(String(32), nullable=False, index=True)
    source_order_id = Column(String(64), default="", index=True)
    metadata_json = Column(Text, default="{}")
    granted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, index=True)


class RefundRequest(Base):
    __tablename__ = "refund_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    order_no = Column(String(64), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(16), default="pending", index=True)
    admin_note = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LlmBillingSettings(Base):
    """单行全局 LLM 计费参数（id=1）；缺省时回退环境变量。"""

    __tablename__ = "llm_billing_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_fee_multiplier = Column(Numeric(8, 4), nullable=True)
    default_input_price_per_1k = Column(Numeric(12, 6), nullable=True)
    default_output_price_per_1k = Column(Numeric(12, 6), nullable=True)
    default_min_charge = Column(Numeric(12, 2), nullable=True)
    official_markup_multiplier = Column(Numeric(8, 4), nullable=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AiModelPrice(Base):
    __tablename__ = "ai_model_prices"
    __table_args__ = (UniqueConstraint("provider", "model", name="uq_ai_model_price"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(64), nullable=False, index=True)
    model = Column(String(256), nullable=False, index=True)
    label = Column(String(256), default="")
    input_price_per_1k = Column(Numeric(12, 6), default=0.0)
    output_price_per_1k = Column(Numeric(12, 6), default=0.0)
    min_charge = Column(Numeric(12, 2), default=0.01)
    official_input_price_per_1k = Column(Numeric(12, 6), nullable=True)
    official_output_price_per_1k = Column(Numeric(12, 6), nullable=True)
    official_min_charge = Column(Numeric(12, 2), nullable=True)
    official_source = Column(String(512), default="")
    official_synced_at = Column(DateTime, nullable=True)
    # 图片生成按「张」计费的单价（元/张）。为空时回退环境默认价。与按 token 的
    # input/output_price_per_1k 互不影响：生图走该列，对话走 token 列。
    price_per_image = Column(Numeric(12, 6), nullable=True)
    enabled = Column(Boolean, default=True, index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LlmModelCapability(Base):
    __tablename__ = "llm_model_capabilities"
    __table_args__ = (UniqueConstraint("provider", "model", name="uq_llm_model_cap"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(64), nullable=False, index=True)
    model = Column(String(256), nullable=False, index=True)
    l1_status = Column(String(32), default="pending", index=True)
    l1_score = Column(Float, nullable=True)
    l1_at = Column(DateTime, nullable=True)
    l1_flags_json = Column(Text, default="{}")
    l1_error = Column(Text, default="")
    effective_category = Column(String(32), default="")
    taxonomy_source = Column(String(32), default="heuristic")
    l3_status = Column(String(32), default="none", index=True)
    l3_notes = Column(Text, default="")
    l3_reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    l3_at = Column(DateTime, nullable=True)
    cs_ticket_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AuthorEarning(Base):
    __tablename__ = "author_earnings"
    __table_args__ = (UniqueConstraint("order_id", name="uq_author_earning_order"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("catalog_items.id"), nullable=True, index=True)
    gross = Column(Numeric(12, 2), nullable=False)
    platform_fee_rate = Column(Numeric(5, 4), nullable=False, default=0.30)
    net = Column(Numeric(12, 2), nullable=False)
    status = Column(String(16), default="pending", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    settled_at = Column(DateTime, nullable=True)


class AuthorWithdrawal(Base):
    __tablename__ = "author_withdrawals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(16), default="pending", index=True)
    admin_note = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    processed_at = Column(DateTime, nullable=True)


class GrayRelease(Base):
    """灰度发布配置：某 catalog 商品某版本按比例/标签放量（阶段 9 MOD 商店后台）。"""

    __tablename__ = "gray_releases"
    __table_args__ = (
        UniqueConstraint("catalog_id", "version", name="uq_gray_release_item_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_id = Column(Integer, ForeignKey("catalog_items.id"), nullable=False, index=True)
    version = Column(String(64), nullable=False, index=True)
    # 放量比例 0.0-1.0（基于 user_id 哈希分桶）。
    rollout_percent = Column(Float, default=0.0)
    # 显式允许的用户标签/分组（JSON 数组），命中即可见，不受比例限制。
    allow_tags_json = Column(Text, default="[]")
    status = Column(
        String(16), default="active", index=True
    )  # active / paused / promoted / rolled_back
    note = Column(Text, default="")
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ModReview(Base):
    """MOD/AI 商品评价（阶段 9）：评分 + 文字，作者可回复。"""

    __tablename__ = "mod_reviews"
    __table_args__ = (UniqueConstraint("catalog_id", "user_id", name="uq_review_item_user"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalog_id = Column(Integer, ForeignKey("catalog_items.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    content = Column(Text, default="")
    author_reply = Column(Text, default="")
    is_hidden = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    order_ids_json = Column(Text, nullable=False, default="[]")
    amount = Column(Numeric(12, 2), nullable=False)
    tax_rate = Column(Numeric(5, 4), default=0.06)
    invoice_type = Column(String(16), default="personal")
    title = Column(String(256), default="")
    tax_no = Column(String(64), default="")
    status = Column(String(16), default="pending", index=True)
    reject_reason = Column(Text, default="")
    pdf_url = Column(String(1024), default="")
    issued_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ReconciliationReport(Base):
    __tablename__ = "reconciliation_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_start = Column(DateTime, nullable=False, index=True)
    period_end = Column(DateTime, nullable=False, index=True)
    total_orders = Column(Integer, default=0)
    total_gmv = Column(Numeric(12, 2), default=0.0)
    platform_revenue = Column(Numeric(12, 2), default=0.0)
    author_payable = Column(Numeric(12, 2), default=0.0)
    refunds_count = Column(Integer, default=0)
    refunds_amount = Column(Numeric(12, 2), default=0.0)
    wallet_top_ups = Column(Numeric(12, 2), default=0.0)
    alipay_income = Column(Numeric(12, 2), default=0.0)
    status = Column(String(16), default="draft", index=True)
    generated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    confirmed_at = Column(DateTime, nullable=True)
