# 数据库迁移指南

迁移链与操作入口见 [迁移注册表](../MIGRATION_REGISTRY.md)，实际版本以 `alembic/versions/` 为准。
新模型和字段须随改动提交经人工审查的 Alembic 迁移；生产 PostgreSQL 的 schema 演进统一走迁移链。桌面 SQLite 的 `create_all` 仅作运行时兜底，不替代迁移。
本地可运行 `python scripts/dev/check_schema_drift.py`；CI 的 Alembic SSOT 检查执行迁移及模型一致性校验。
