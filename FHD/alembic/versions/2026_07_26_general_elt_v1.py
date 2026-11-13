"""通用 ETL V1 数据模型。

Revision ID: 2026_07_26_general_elt_v1
Revises: 2026_07_24_shipment_elt_fingerprints
Create Date: 2026-07-26
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_26_general_etl_v1"
down_revision: Union[str, Sequence[str], None] = "2026_07_24_shipment_etl_fingerprints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tenant_owner_columns() -> list[sa.Column]:
    return [
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
    ]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    ]


_ETL_PERMISSIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("elt.read", "查看数据对接", ("viewer", "operator", "admin")),
    ("elt.template.manage", "管理 ELT 模板", ("operator", "admin")),
    ("elt.execute", "执行 ELT", ("operator", "admin")),
    ("elt.rollback", "撤销 ELT", ("admin",)),
    ("elt.target.manage", "管理 ETL 目标", ("admin",)),
)


def _seed_elt_permissions(bind) -> None:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if not {"permissions", "roles", "role_permissions"}.issubset(tables):
        return
    for code, name, role_names in _ETL_PERMISSIONS:
        permission_id = bind.execute(
            sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": code}
        ).scalar()
        if permission_id is None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO permissions (name, code, description, module, created_at)
                    VALUES (:name, :code, :description, :module, :created_at)
                    """
                ),
                {
                    "name": name,
                    "code": code,
                    "description": "",
                    "module": "elt",
                    "created_at": datetime.utcnow(),
                },
            )
            permission_id = bind.execute(
                sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": code}
            ).scalar()
        for role_name in role_names:
            role_id = bind.execute(
                sa.text("SELECT id FROM roles WHERE name = :name"), {"name": role_name}
            ).scalar()
            if role_id is None or permission_id is None:
                continue
            exists = bind.execute(
                sa.text(
                    """
                    SELECT 1 FROM role_permissions
                    WHERE role_id = :role_id AND permission_id = :permission_id
                    """
                ),
                {"role_id": role_id, "permission_id": permission_id},
            ).first()
            if not exists:
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO role_permissions (role_id, permission_id)
                        VALUES (:role_id, :permission_id)
                        """
                    ),
                    {"role_id": role_id, "permission_id": permission_id},
                )


def upgrade() -> None:
    # Squashed baseline 会用“当前” Base.metadata 创建全量 ORM 表；新库因此已经
    # 拥有本迁移的六张表。存量库从旧 head 升级时则一张都没有。
    bind = op.get_bind()
    _seed_elt_permissions(bind)
    existing = set(sa.inspect(bind).get_table_names())
    required = {
        "elt_uploads",
        "elt_templates",
        "elt_template_versions",
        "elt_runs",
        "elt_run_rows",
        "elt_target_configs",
    }
    if required.issubset(existing):
        return
    partial = required & existing
    if partial:
        raise RuntimeError(f"通用 ETL 表处于不完整状态，拒绝继续迁移: {sorted(partial)}")

    op.create_table(
        "elt_uploads",
        sa.Column("id", sa.String(36), primary_key=True),
        *_tenant_owner_columns(),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("suffix", sa.String(16), nullable=False),
        sa.Column("content_type", sa.String(128)),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_elt_uploads_tenant_id", "elt_uploads", ["tenant_id"])
    op.create_index("ix_elt_uploads_owner_user_id", "elt_uploads", ["owner_user_id"])
    op.create_index("ix_elt_upload_owner", "elt_uploads", ["tenant_id", "owner_user_id"])
    op.create_index(
        "ix_elt_upload_sha256", "elt_uploads", ["tenant_id", "owner_user_id", "sha256"]
    )

    op.create_table(
        "elt_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        *_tenant_owner_columns(),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("description", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id", "owner_user_id", "name", name="uq_elt_template_owner_name"
        ),
    )
    op.create_index("ix_elt_templates_tenant_id", "elt_templates", ["tenant_id"])
    op.create_index("ix_elt_templates_owner_user_id", "elt_templates", ["owner_user_id"])
    op.create_index("ix_elt_templates_target_type", "elt_templates", ["target_type"])
    op.create_index("ix_elt_template_owner", "elt_templates", ["tenant_id", "owner_user_id"])

    op.create_table(
        "elt_template_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("template_id", sa.String(36), sa.ForeignKey("elt_templates.id"), nullable=False),
        *_tenant_owner_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("source_features_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("field_mappings_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("validation_rules_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("match_keys_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("allowed_update_fields_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("action_rules_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("template_id", "version", name="uq_elt_template_version"),
    )
    op.create_index("ix_elt_template_versions_template_id", "elt_template_versions", ["template_id"])
    op.create_index("ix_elt_template_versions_tenant_id", "elt_template_versions", ["tenant_id"])
    op.create_index(
        "ix_elt_template_versions_owner_user_id", "elt_template_versions", ["owner_user_id"]
    )
    op.create_index(
        "ix_elt_template_version_owner",
        "elt_template_versions",
        ["tenant_id", "owner_user_id"],
    )

    op.create_table(
        "elt_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        *_tenant_owner_columns(),
        sa.Column("upload_id", sa.String(36), sa.ForeignKey("elt_uploads.id"), nullable=False),
        sa.Column("template_id", sa.String(36), sa.ForeignKey("elt_templates.id")),
        sa.Column(
            "template_version_id", sa.String(36), sa.ForeignKey("elt_template_versions.id")
        ),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("source_features_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("draft_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("receipt_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("update_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skip_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("executed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reversible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rollback_status", sa.String(32)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in (
        "tenant_id",
        "owner_user_id",
        "upload_id",
        "template_id",
        "template_version_id",
        "target_type",
    ):
        op.create_index(f"ix_elt_runs_{column}", "elt_runs", [column])
    op.create_index(
        "ix_elt_run_owner_created", "elt_runs", ["tenant_id", "owner_user_id", "created_at"]
    )
    op.create_index("ix_elt_run_status", "elt_runs", ["status"])

    op.create_table(
        "elt_run_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("elt_runs.id"), nullable=False),
        *_tenant_owner_columns(),
        sa.Column("source_sheet", sa.String(160), nullable=False, server_default=""),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("source_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("normalized_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("provenance_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("validation_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("llm_suggestion_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("suggested_action", sa.String(16), nullable=False, server_default="skip"),
        sa.Column("final_action", sa.String(16), nullable=False, server_default="skip"),
        sa.Column("action_overridden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("match_ref", sa.String(128)),
        sa.Column("before_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("after_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("execution_status", sa.String(32)),
        sa.Column("execution_error_code", sa.String(64)),
        sa.Column("execution_error_message", sa.String(500)),
        *_timestamps(),
        sa.UniqueConstraint("run_id", "source_sheet", "source_row", name="uq_elt_run_source_row"),
    )
    op.create_index("ix_elt_run_rows_run_id", "elt_run_rows", ["run_id"])
    op.create_index("ix_elt_run_rows_tenant_id", "elt_run_rows", ["tenant_id"])
    op.create_index("ix_elt_run_rows_owner_user_id", "elt_run_rows", ["owner_user_id"])
    op.create_index(
        "ix_elt_run_rows_owner", "elt_run_rows", ["tenant_id", "owner_user_id"]
    )
    op.create_index(
        "ix_elt_run_rows_run_action", "elt_run_rows", ["run_id", "final_action"]
    )

    op.create_table(
        "elt_target_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        *_tenant_owner_columns(),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False, server_default="webhook"),
        sa.Column("endpoint_url", sa.Text(), nullable=False),
        sa.Column("headers_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("secret_ref", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id", "owner_user_id", "name", name="uq_elt_target_config_owner_name"
        ),
    )
    op.create_index("ix_elt_target_configs_tenant_id", "elt_target_configs", ["tenant_id"])
    op.create_index(
        "ix_elt_target_configs_owner_user_id", "elt_target_configs", ["owner_user_id"]
    )
    op.create_index(
        "ix_elt_target_config_owner",
        "elt_target_configs",
        ["tenant_id", "owner_user_id"],
    )


def downgrade() -> None:
    for table in (
        "elt_target_configs",
        "elt_run_rows",
        "elt_runs",
        "elt_template_versions",
        "elt_templates",
        "elt_uploads",
    ):
        op.drop_table(table)
