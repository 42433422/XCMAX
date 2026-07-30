"""数据库种子包。

提供 ``WorkflowDefinition``、初始单据模板等核心配置数据的幂等种子，便于在
初始化或迁移后快速建立可执行的端到端编排链路与开箱演示能力。
"""

from __future__ import annotations

from app.db.seeds.document_templates_seed import ensure_initial_document_templates

__all__ = ["ensure_initial_document_templates"]
