"""Legacy raw-SQL tables that have no ORM bootstrap, plus template compatibility."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import DDL, text
from sqlalchemy.engine import Engine

from app.db.bootstrap.contracts import InspectorFactory, SqliteConnection


def init_distillation_tables(engine: Engine) -> None:
    if engine.dialect.name == "sqlite":
        statements = (
            """
            CREATE TABLE IF NOT EXISTS distillation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL, intent TEXT NOT NULL,
                slots TEXT, confidence REAL DEFAULT 1.0,
                source TEXT DEFAULT 'manual', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_for_training INTEGER DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS training_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT, intent TEXT NOT NULL, count INTEGER DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )
    else:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS distillation_log (
                id BIGSERIAL PRIMARY KEY, query TEXT NOT NULL, intent TEXT NOT NULL,
                slots TEXT, confidence DOUBLE PRECISION DEFAULT 1.0,
                source TEXT DEFAULT 'manual', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_for_training INTEGER DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS training_stats (
                id BIGSERIAL PRIMARY KEY, intent TEXT NOT NULL, count INTEGER DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(DDL(statement))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS idx_intent ON distillation_log(intent)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS idx_used ON distillation_log(used_for_training)")
        )


def init_extract_logs_tables(engine: Engine) -> None:
    primary_key = (
        "INTEGER PRIMARY KEY AUTOINCREMENT"
        if engine.dialect.name == "sqlite"
        else "BIGSERIAL PRIMARY KEY"
    )
    if primary_key == "INTEGER PRIMARY KEY AUTOINCREMENT":
        statement = """
            CREATE TABLE IF NOT EXISTS extract_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT, file_path TEXT, data_type TEXT,
                total_rows INTEGER DEFAULT 0, valid_rows INTEGER, imported_rows INTEGER,
                skipped_rows INTEGER, failed_rows INTEGER, status TEXT DEFAULT 'pending',
                error_message TEXT, field_mapping TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
    else:
        statement = """
            CREATE TABLE IF NOT EXISTS extract_logs (
                id BIGSERIAL PRIMARY KEY, file_name TEXT, file_path TEXT, data_type TEXT,
                total_rows INTEGER DEFAULT 0, valid_rows INTEGER, imported_rows INTEGER,
                skipped_rows INTEGER, failed_rows INTEGER, status TEXT DEFAULT 'pending',
                error_message TEXT, field_mapping TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
    with engine.begin() as connection:
        connection.execute(DDL(statement))


@dataclass(frozen=True)
class TemplateTables:
    sqlite_connect: SqliteConnection
    inspect: InspectorFactory

    def init_template_tables(self, db_path: str) -> None:
        """
        初始化模板相关表：
        - templates
        - template_usage_log

        兼容策略：
        - 表不存在时创建
        - 表已存在但缺少新字段时自动补齐
        """
        with self.sqlite_connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "\n            CREATE TABLE IF NOT EXISTS templates (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                template_key TEXT,\n                template_name TEXT NOT NULL,\n                template_type TEXT,\n                original_file_path TEXT,\n                analyzed_data TEXT,\n                editable_config TEXT,\n                zone_config TEXT,\n                merged_cells_config TEXT,\n                style_config TEXT,\n                business_rules TEXT,\n                is_active INTEGER DEFAULT 1,\n                tenant_id INTEGER,\n                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n            )\n            "
            )
            cur.execute(
                "\n            CREATE TABLE IF NOT EXISTS template_usage_log (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                template_id INTEGER NOT NULL,\n                action TEXT NOT NULL,\n                result TEXT,\n                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n            )\n            "
            )
            cur.execute(
                "\n            CREATE INDEX IF NOT EXISTS idx_templates_type_active\n            ON templates (template_type, is_active)\n            "
            )
            cur.execute(
                "\n            CREATE INDEX IF NOT EXISTS idx_template_usage_log_template_id\n            ON template_usage_log (template_id)\n            "
            )
            cur.execute("PRAGMA table_info(templates)")
            templates_columns = {str(row[1]).strip() for row in cur.fetchall() or []}
            required_templates_columns = {
                "template_key": "ALTER TABLE templates ADD COLUMN template_key TEXT",
                "template_name": "ALTER TABLE templates ADD COLUMN template_name TEXT",
                "template_type": "ALTER TABLE templates ADD COLUMN template_type TEXT",
                "original_file_path": "ALTER TABLE templates ADD COLUMN original_file_path TEXT",
                "analyzed_data": "ALTER TABLE templates ADD COLUMN analyzed_data TEXT",
                "editable_config": "ALTER TABLE templates ADD COLUMN editable_config TEXT",
                "zone_config": "ALTER TABLE templates ADD COLUMN zone_config TEXT",
                "merged_cells_config": "ALTER TABLE templates ADD COLUMN merged_cells_config TEXT",
                "style_config": "ALTER TABLE templates ADD COLUMN style_config TEXT",
                "business_rules": "ALTER TABLE templates ADD COLUMN business_rules TEXT",
                "is_active": "ALTER TABLE templates ADD COLUMN is_active INTEGER DEFAULT 1",
                "created_at": "ALTER TABLE templates ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "updated_at": "ALTER TABLE templates ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "tenant_id": "ALTER TABLE templates ADD COLUMN tenant_id INTEGER",
            }
            for column_name, sql in required_templates_columns.items():
                if column_name not in templates_columns:
                    cur.execute(sql)
            cur.execute("PRAGMA table_info(template_usage_log)")
            usage_columns = {str(row[1]).strip() for row in cur.fetchall() or []}
            required_usage_columns = {
                "template_id": "ALTER TABLE template_usage_log ADD COLUMN template_id INTEGER",
                "action": "ALTER TABLE template_usage_log ADD COLUMN action TEXT",
                "result": "ALTER TABLE template_usage_log ADD COLUMN result TEXT",
                "created_at": "ALTER TABLE template_usage_log ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            }
            for column_name, sql in required_usage_columns.items():
                if column_name not in usage_columns:
                    cur.execute(sql)
            conn.commit()

    def init_template_tables_for_engine(self, engine: Engine) -> None:
        """
        在主库（PostgreSQL）上创建 templates / template_usage_log。
        与 Alembic f0c2a8e1_templates 对齐；启动时幂等补齐，便于未跑迁移的环境。
        """
        if engine.dialect.name != "postgresql":
            return
        insp = self.inspect(engine)
        existing = set(insp.get_table_names())
        with engine.begin() as conn:
            if "templates" not in existing:
                conn.execute(
                    text(
                        "\n                    CREATE TABLE templates (\n                        id BIGSERIAL PRIMARY KEY,\n                        template_key TEXT,\n                        template_name TEXT NOT NULL,\n                        template_type TEXT,\n                        original_file_path TEXT,\n                        analyzed_data TEXT,\n                        editable_config TEXT,\n                        zone_config TEXT,\n                        merged_cells_config TEXT,\n                        style_config TEXT,\n                        business_rules TEXT,\n                        is_active INTEGER DEFAULT 1,\n                        tenant_id INTEGER,\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    "
                    )
                )
            if "template_usage_log" not in existing:
                conn.execute(
                    text(
                        "\n                    CREATE TABLE template_usage_log (\n                        id BIGSERIAL PRIMARY KEY,\n                        template_id BIGINT NOT NULL REFERENCES templates(id) ON DELETE CASCADE,\n                        action TEXT NOT NULL,\n                        result TEXT,\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    "
                    )
                )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_templates_type_active ON templates (template_type, is_active)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_template_usage_log_template_id ON template_usage_log (template_id)"
                )
            )
