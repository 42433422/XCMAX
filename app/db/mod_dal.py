"""
mod_dal.py — Mod 数据访问层（DAL）抽象

设计目标
========
将「按 Mod 隔离的多数据库副本」从散落各处的内联逻辑收敛到统一的 DAL 接口。

问题背景
========
原先的 ``ensure_sqlite_per_mod_database_copies`` 函数工作良好，但它暴露的是
**文件级操作**（shutil.copy2）。调用方需要关心：
  - 母库路径在哪？
  - 目标文件名怎么算？
  - 跨库事务如何处理？
  - 失败如何回滚？

这导致：
  1. 业务层容易绕过 DAL 直接碰底层文件
  2. SQLite → PostgreSQL 切换时改动面巨大
  3. 跨 Mod 事务无法在 DAL 层做补偿

DAL 接口
========
本模块提供 ``ModDataAccessLayer`` 协议类，所有 Mod 数据访问都应通过它。
具体实现分两种：
  - ``SQLiteModDAL``：使用母库副本 + 独立 SQLite 文件（默认桌面）
  - ``PostgresModDAL``：schema 隔离（默认）或 ``XCAGI_MOD_ISOLATED_DATABASES=1`` 时独立库

使用示例
========
    from app.db.mod_dal import get_mod_dal

    dal = get_mod_dal()
    session = dal.open_session(mod_id="taiyangniao-pro")
    rows = dal.execute(session, "SELECT * FROM products WHERE id = ?", (42,))
    dal.close_session(session)
"""
from __future__ import annotations

import abc
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable


@dataclass(frozen=True)
class ModDBRef:
    """Mod 数据库引用（不暴露物理路径）"""
    mod_id: str
    logical_name: str  # 例如 "products" / "orders" / "analytics"

    @property
    def key(self) -> str:
        return f"{self.logical_name}::{self.mod_id}"


@runtime_checkable
class ModDataAccessLayer(Protocol):
    """Mod DAL 协议（PEP 544）"""
    backend: str  # "sqlite" / "postgres"

    def open_session(self, mod_id: str) -> Any: ...
    def close_session(self, session: Any) -> None: ...
    def execute(self, session: Any, sql: str, params: tuple = ()) -> list[dict]: ...
    def list_tables(self, mod_id: str, logical_name: str) -> list[str]: ...
    def backup_mod_database(self, mod_id: str, dest: Path) -> Path: ...
    def healthcheck(self) -> dict: ...


class SQLiteModDAL:
    """
    SQLite Mod DAL：每 Mod 独立 .db 文件，从母库一次性 seed。

    与 ``ensure_sqlite_per_mod_database_copies`` 的差异：
      - 对外只暴露「Mod 标识」+「逻辑库名」，不暴露路径
      - ``open_session`` 自动按需触发 seed copy（不强制在 lifespan 阶段预热）
      - ``backup_mod_database`` 使用 SQLite 在线备份 API（不阻塞读写）
    """
    backend = "sqlite"

    def __init__(self, work_dir: str | None = None) -> None:
        from app.db.init_db import get_app_data_dir, DEFAULT_DB_FILES
        from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix

        self._work_dir = Path(work_dir or get_app_data_dir())
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._default_files = list(DEFAULT_DB_FILES)
        self._ensure_seed = _EnsureSeed(self._work_dir, sqlite_filename_with_mod_suffix)
        self._connections: dict[str, sqlite3.Connection] = {}

    def _resolve_path(self, mod_id: str, logical_name: str) -> Path:
        """解析 Mod 数据库文件路径（私有，外部禁止直接使用）"""
        from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix

        logical_name = logical_name if logical_name.endswith(".db") else f"{logical_name}.db"
        if mod_id in ("", "default", "global"):
            return self._work_dir / logical_name
        return self._work_dir / sqlite_filename_with_mod_suffix(logical_name, mod_id)

    def _ensure_seeded(self, mod_id: str, logical_name: str) -> Path:
        """按需触发母库复制（首次访问时）"""
        target = self._resolve_path(mod_id, logical_name)
        if target.exists():
            return target
        # 母库 = 去掉 mod 后缀的同 stem 文件
        seed_name = logical_name if logical_name.endswith(".db") else f"{logical_name}.db"
        seed = self._work_dir / seed_name
        if not seed.exists():
            raise FileNotFoundError(
                f"母库不存在 {seed}（无法为 Mod {mod_id} 准备 {target.name}）"
            )
        # 复用 init_db 的复制逻辑（保证一致性）
        self._ensure_seed(mod_id, seed_name)
        return target

    def open_session(self, mod_id: str) -> sqlite3.Connection:
        key = f"{mod_id}"
        if key in self._connections:
            return self._connections[key]
        # 默认连主库 products；如需其他库由调用方指定 logical_name
        path = self._ensure_seeded(mod_id, "products")
        conn = sqlite3.connect(
            str(path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        self._connections[key] = conn
        return conn

    def close_session(self, session: sqlite3.Connection) -> None:
        try:
            session.close()
        except Exception:  # pragma: no cover
            pass

    def execute(
        self,
        session: sqlite3.Connection,
        sql: str,
        params: tuple = (),
    ) -> list[dict]:
        cur = session.execute(sql, params)
        if cur.description is None:
            session.commit()
            return []
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def list_tables(self, mod_id: str, logical_name: str = "products") -> list[str]:
        path = self._ensure_seeded(mod_id, logical_name)
        conn = sqlite3.connect(str(path))
        try:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            return [r[0] for r in cur.fetchall()]
        finally:
            conn.close()

    def backup_mod_database(self, mod_id: str, dest: Path) -> Path:
        """使用 SQLite 在线备份 API（不阻塞读写）"""
        src_path = self._ensure_seeded(mod_id, "products")
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(str(src_path))
        dst = sqlite3.connect(str(dest))
        try:
            with dst:
                src.backup(dst)
        finally:
            src.close()
            dst.close()
        return dest

    def healthcheck(self) -> dict:
        return {
            "backend": self.backend,
            "work_dir": str(self._work_dir),
            "open_sessions": len(self._connections),
            "default_files": self._default_files,
            "caching": "XCAGI_SQLITE_PER_MOD_COPIES=1" if os.environ.get("XCAGI_SQLITE_PER_MOD_COPIES", "1") != "0" else "disabled",
        }

    def ensure_mod_copies(self, mod_ids: Iterable[str]) -> dict[str, Any]:
        """启动时预热 Mod SQLite 副本（经 DAL 单例，内部复用 init_db 复制逻辑）。"""
        from app.db.init_db import ensure_sqlite_per_mod_database_copies, sqlite_per_mod_copies_enabled

        ids = [m for m in mod_ids if m]
        if not ids or not sqlite_per_mod_copies_enabled():
            return {"warmed": 0, "skipped": True, "reason": "disabled_or_empty"}
        ensure_sqlite_per_mod_database_copies(ids)
        return {"warmed": len(ids), "skipped": False, "healthcheck": self.healthcheck()}


def _postgres_mod_isolated_databases() -> bool:
    return (os.environ.get("XCAGI_MOD_ISOLATED_DATABASES") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _mod_schema_name(mod_id: str) -> str:
    from app.db.sqlite_mod_paths import mod_suffix_token

    suffix = mod_suffix_token(mod_id) or "default"
    return f"mod_{suffix}"


def _adapt_sqlite_placeholders(sql: str, params: tuple) -> tuple[str, dict[str, Any]]:
    """将 SQLite ``?`` 占位转为 SQLAlchemy 命名绑定（PG 路径复用 DAL 调用方 SQL）。"""
    if "?" not in sql:
        return sql, {f"p{i}": v for i, v in enumerate(params)}
    parts = sql.split("?")
    if len(parts) != len(params) + 1:
        return sql, {f"p{i}": v for i, v in enumerate(params)}
    out: list[str] = []
    bind: dict[str, Any] = {}
    for i, part in enumerate(parts[:-1]):
        key = f"p{i}"
        out.append(part)
        out.append(f":{key}")
        bind[key] = params[i]
    out.append(parts[-1])
    return "".join(out), bind


class PostgresModDAL:
    """
    PostgreSQL Mod DAL：每 Mod 独立 schema（``mod_{suffix}``）或独立库（``XCAGI_MOD_ISOLATED_DATABASES``）。
    """

    backend = "postgres"

    def __init__(self, database_url: str | None = None) -> None:
        from app.db import _create_engine_for_url
        from app.db.init_db import DEFAULT_DB_FILES

        self._base_url = (database_url or os.environ.get("DATABASE_URL", "")).strip()
        if not self._base_url:
            raise ValueError("PostgresModDAL 需要 DATABASE_URL")
        self._engine = _create_engine_for_url(self._base_url)
        self._isolated_db = _postgres_mod_isolated_databases()
        self._default_files = list(DEFAULT_DB_FILES)
        self._connections: dict[str, Any] = {}
        self._schemas_ready: set[str] = set()

    def _engine_for_mod(self, mod_id: str):
        if mod_id in ("", "default", "global") or not self._isolated_db:
            return self._engine
        from app.db import _create_engine_for_url, _postgres_url_with_mod_db

        url = _postgres_url_with_mod_db(self._base_url, mod_id)
        return _create_engine_for_url(url)

    def _ensure_schema(self, mod_id: str) -> str:
        if self._isolated_db:
            return "public"
        schema = _mod_schema_name(mod_id)
        if schema in self._schemas_ready:
            return schema
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        self._schemas_ready.add(schema)
        return schema

    def open_session(self, mod_id: str) -> Any:
        from sqlalchemy import text

        key = mod_id or "default"
        if key in self._connections:
            return self._connections[key]
        engine = self._engine_for_mod(mod_id)
        conn = engine.connect()
        if not self._isolated_db:
            schema = self._ensure_schema(mod_id)
            conn.execute(text(f'SET search_path TO "{schema}", public'))
        self._connections[key] = conn
        return conn

    def close_session(self, session: Any) -> None:
        try:
            session.close()
        except Exception:  # pragma: no cover
            pass
        for key, conn in list(self._connections.items()):
            if conn is session:
                del self._connections[key]
                break

    def execute(self, session: Any, sql: str, params: tuple = ()) -> list[dict]:
        from sqlalchemy import text

        sql_adapted, bind = _adapt_sqlite_placeholders(sql, params)
        result = session.execute(text(sql_adapted), bind)
        if result.returns_rows:
            return [dict(row._mapping) for row in result]
        session.commit()
        return []

    def list_tables(self, mod_id: str, logical_name: str = "products") -> list[str]:
        from sqlalchemy import text

        schema = "public" if self._isolated_db else _mod_schema_name(mod_id)
        engine = self._engine_for_mod(mod_id)
        with engine.connect() as conn:
            if not self._isolated_db:
                conn.execute(text(f'SET search_path TO "{schema}", public'))
            rows = conn.execute(
                text(
                    "SELECT tablename FROM pg_catalog.pg_tables "
                    "WHERE schemaname = :schema ORDER BY tablename"
                ),
                {"schema": schema},
            ).fetchall()
        return [str(r[0]) for r in rows]

    def backup_mod_database(self, mod_id: str, dest: Path) -> Path:
        """PG：导出 Mod schema 到 SQL 文件（需 pg_dump 或回退为逻辑提示）。"""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        schema = _mod_schema_name(mod_id)
        import shutil
        import subprocess

        if shutil.which("pg_dump"):
            from sqlalchemy.engine import make_url

            u = make_url(self._base_url)
            cmd = [
                "pg_dump",
                "--schema-only",
                f"--schema={schema}",
                "-h",
                u.host or "localhost",
                "-p",
                str(u.port or 5432),
                "-U",
                u.username or "xcagi",
                "-d",
                u.database or "xcagi",
                "-f",
                str(dest),
            ]
            env = os.environ.copy()
            if u.password:
                env["PGPASSWORD"] = str(u.password)
            subprocess.run(cmd, check=True, env=env, capture_output=True)
            return dest
        # 无 pg_dump：写入占位说明，供运维改用 DR runbook
        dest.write_text(
            f"-- Mod backup placeholder for schema {schema}; install pg_dump for full export\n",
            encoding="utf-8",
        )
        return dest

    def healthcheck(self) -> dict:
        from sqlalchemy.engine import make_url

        host = "unknown"
        try:
            u = make_url(self._base_url)
            host = u.host or "localhost"
        except Exception:
            pass
        return {
            "backend": self.backend,
            "host": host,
            "isolated_databases": self._isolated_db,
            "open_sessions": len(self._connections),
            "default_files": self._default_files,
            "schemas_ready": len(self._schemas_ready),
        }

    def ensure_mod_copies(self, mod_ids: Iterable[str]) -> dict[str, Any]:
        """PG：确保每 Mod 的 schema（或独立库已由 bootstrap 脚本创建）存在。"""
        ids = [m for m in mod_ids if m]
        if not ids:
            return {"warmed": 0, "skipped": True, "reason": "empty"}
        if self._isolated_db:
            return {
                "warmed": len(ids),
                "skipped": False,
                "note": "isolated_db; run scripts/bootstrap_mod_dbs.py if DB missing",
                "healthcheck": self.healthcheck(),
            }
        for mid in ids:
            self._ensure_schema(mid)
        return {"warmed": len(ids), "skipped": False, "healthcheck": self.healthcheck()}


class _EnsureSeed:
    """薄包装，复用 init_db 的母库复制逻辑（保证一致性）"""

    def __init__(self, work_dir: Path, suffix_fn) -> None:
        self._work_dir = work_dir
        self._suffix_fn = suffix_fn

    def __call__(self, mod_id: str, db_filename: str) -> None:
        # 委托给 init_db 的 ensure_sqlite_per_mod_database_copies
        from app.db.init_db import ensure_sqlite_per_mod_database_copies

        ensure_sqlite_per_mod_database_copies([mod_id], db_files=[db_filename])


# ===== 单例（DAL 全应用共用一份）=====
_dal_singleton: ModDataAccessLayer | None = None


def get_mod_dal(force_new: bool = False) -> ModDataAccessLayer:
    """
    获取 Mod DAL 单例。

    桌面/dev：SQLite Mod 副本（``SQLiteModDAL``）。
    生产/staging + PostgreSQL 主库：PG DAL 落地前 **禁止** 静默回退 SQLite
    （须显式 ``XCAGI_MOD_DAL_ALLOW_SQLITE_FALLBACK=1`` 或改用 SQLite 主库）。
    """
    global _dal_singleton
    if _dal_singleton is not None and not force_new:
        return _dal_singleton

    from app.utils.deployment import mod_dal_sqlite_fallback_allowed

    database_url = os.environ.get("DATABASE_URL", "sqlite:///./data/products.db")
    if database_url.startswith("sqlite"):
        _dal_singleton = SQLiteModDAL()
    elif database_url.startswith("postgresql") or database_url.startswith("postgres"):
        if mod_dal_sqlite_fallback_allowed() and os.environ.get(
            "XCAGI_MOD_DAL_ALLOW_SQLITE_FALLBACK", ""
        ).strip().lower() in {"1", "true", "yes", "on"}:
            import logging

            logging.getLogger(__name__).warning(
                "DATABASE_URL 为 PostgreSQL 但 XCAGI_MOD_DAL_ALLOW_SQLITE_FALLBACK=1；"
                "使用 SQLite Mod DAL（勿用于生产签约部署）"
            )
            _dal_singleton = SQLiteModDAL()
        else:
            _dal_singleton = PostgresModDAL(database_url=database_url)
    elif mod_dal_sqlite_fallback_allowed():
        import logging

        logging.getLogger(__name__).warning(
            "非 PostgreSQL/SQLite URL；回退 SQLite Mod DAL"
        )
        _dal_singleton = SQLiteModDAL()
    else:
        raise RuntimeError(
            "DATABASE_URL 为 PostgreSQL，但 Mod DAL 初始化失败。"
            "生产/staging 禁止静默回退 SQLite。"
            "可选：桌面模式 (XCAGI_DESKTOP_MODE=1)、开发显式 "
            "XCAGI_MOD_DAL_ALLOW_SQLITE_FALLBACK=1、或暂用 sqlite:/// 主库。"
        )
    return _dal_singleton


def reset_mod_dal_singleton() -> None:
    """测试用：重置单例。"""
    global _dal_singleton
    _dal_singleton = None
