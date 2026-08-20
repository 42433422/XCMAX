// CI SSOT: generated from config/database_storage_modes.yaml — DO NOT EDIT BY HAND
// 改数据库存储模式请编辑该 yaml 后运行: python scripts/dev/database_storage_ssot.py generate --apply

export type DatabaseStorageModeId = 'local_sqlite' | 'remote_postgresql';

export const DEFAULT_DATABASE_STORAGE_MODE: DatabaseStorageModeId = 'local_sqlite';
export const DATABASE_STORAGE_MODE_IDS = [
  "local_sqlite",
  "remote_postgresql"
] as const;
export const DATABASE_STORAGE_MODES = [
  {
    "id": "local_sqlite",
    "label": "本地数据库（SQLite）",
    "engine": "sqlite",
    "profileMode": "local",
    "desktopProfilePath": "<desktop-data-dir>/config/database.json",
    "summary": "默认本地数据库，数据留在桌面端 userData。",
    "requiresDatabaseUrl": false,
    "vectorIndexReady": false
  },
  {
    "id": "remote_postgresql",
    "label": "PostgreSQL（PG）",
    "engine": "postgresql",
    "profileMode": "remote",
    "desktopProfilePath": "<desktop-data-dir>/config/database.json",
    "summary": "性能模式数据库，支持长期记忆、向量索引和高并发协作。",
    "requiresDatabaseUrl": true,
    "vectorIndexReady": true
  }
];
export const DATABASE_STORAGE_TRANSITIONS = {
  "sqlite_to_postgresql": {
    "from": "local_sqlite",
    "to": "remote_postgresql",
    "requires_backup": true,
    "requires_alembic_upgrade": true,
    "sync_strategy": "copy_sqlite_tables_to_postgresql_then_switch_profile",
    "sync_command": "python scripts/migrate_sqlite_to_postgres.py --sqlite-path <desktop-sqlite-db> --database-url <postgres-url>",
    "profile_path": "<desktop-data-dir>/config/database.json",
    "restart_required": true
  },
  "postgresql_to_sqlite": {
    "from": "remote_postgresql",
    "to": "local_sqlite",
    "allowed": false,
    "reason": "PostgreSQL 回退 SQLite 需要显式导出/导入，避免误覆盖生产数据。"
  }
};
