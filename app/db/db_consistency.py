"""SQLite 多 DB 副本一致性统一管理层。

背景
----
FHD 桌面/服务端同时存在:

- ``DATABASE_URL`` 主库 (默认 PostgreSQL, 桌面 SQLite);
- 客户端库的 ``app.application.customer_app_service`` 复用同一连接串;
- 启用 ``XCAGI_MOD_ISOLATED_DATABASES`` 时,每个 Mod 走自己的 PostgreSQL 库
  ``<原库>__<MOD>``;
- 桌面 SQLite 启用 ``XCAGI_SQLITE_PER_MOD_COPIES`` 时,每个 Mod 走自己的
  SQLite 文件 ``<原文件名>.<MOD>.db``;
- 内存测试库 ``sqlite:///:memory:`` 通过 ``app.db.test_db_manager`` 注入。

旧实现里这些 DB 各自缓存,互不感知,出现:

1. 同一逻辑库因 URL 字符串拼写不同(有无 mod suffix、有无密码 mask)被识别
   为两条 URL,缓存出两个 engine,读写分离;
2. 线程 A 处于 Mod X、线程 B 处于 Mod Y 时,``_get_engine`` 不加锁 → 同时
   各自 new 一个 engine,内存里残留两套 session local;
3. SQLite 是单写者,即使共用同一文件,两 engine 同时写也会
   ``database is locked``;旧代码靠 ``sqlite_write_guard`` 串行化,但只覆盖
   桌面写路径,服务路径/CLI 路径没被纳入;
4. ``_EngineProxy`` 每次 ``__getattr__`` 都重新 ``_get_engine()``,URL 可能
   因为 mod 中途变化而漂移到另一个 engine,造成"看起来同库实则异库"。

本模块用一个集中管理器把这些路径收口:

- 规范化 URL(密码不脱敏、``sqlite:///`` 与 ``sqlite:////`` 等价、空格折叠);
- ``get_engine()`` / ``get_session_factory()`` 全部在 ``_LOCK`` 内完成
  "URL 解析 + engine/session 缓存"原子段;
- 提供 ``transaction(mod_id=...)`` 上下文管理器,统一 commit/rollback;
- 维护 ``_active_mod_index`` 记录"上一次解析时用的是哪个 Mod",mod 切换时
  自动 ``dispose`` 旧 engine(避免连接被 mod 切走时仍持有旧句柄);
- 暴露 ``invalidate_all()`` 让测试在 ``restore_app_package`` 后一键清空。

所有外部入口必须经 ``app.db`` 调用,本模块仅作为内部实现细节。
"""
from __future__ import annotations

import logging
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------- URL 规范化


# 同逻辑库的不同 URL 写法需要归一化,避免 cache miss → 多 engine 竞争。
_QUOTED_RE = re.compile(r"\s+")
_SQLITE_SCHEMES = {"sqlite", "sqlite+pysqlite", "sqlite+aiosqlite", "sqlite+pysqlcipher"}


def canonicalize_database_url(url: str) -> str:
    """把 ``url`` 折成"同逻辑库同 cache key"的标准形式。

    规则:
    - ``sqlite:////abs/path`` 和 ``sqlite:///abs/path`` 视为同一库;
    - SQLite 内存库 ``:memory:`` 保留原样;
    - query string (``?a=b&c=d``) 在 SQLite 路径下被丢弃 → 同库同 key;
    - 用户名/密码/host/端口保留 → 区分多租户;
    - ``render_as_string(hide_password=False)`` 让密码不被 ``***`` 替换(防
      ``u:p@host`` 与 ``u:***@host`` 被识别成两个 key)。
    """
    if not url:
        return url
    try:
        u = make_url(url)
    except Exception:
        return _QUOTED_RE.sub("", url).strip()
    try:
        if u.get_dialect().name == "sqlite":
            ident = (u.database or "").strip()
            # 内存库直接保留,不做路径归一化(多个 ":memory:" 应该是不同连接)
            if ident in ("", ":memory:"):
                return u.render_as_string(hide_password=False)
            # 统一 ``sqlite:////abs/path`` 形式
            if u.drivername in {"sqlite", "sqlite+pysqlite"} and not ident.startswith("/"):
                u = u.set(database=f"/{ident}")
            # 同库不同 query 视为同 key:删除 query
            if u.query:
                u = u._replace(query={})
        return u.render_as_string(hide_password=False)
    except Exception:
        return _QUOTED_RE.sub("", url).strip()


# ----------------------------------------------------------- engine / session 池


@dataclass
class _CachedBinding:
    """缓存 (URL → engine, session_factory) 的最小元组。"""

    engine: Engine
    session_factory: sessionmaker
    last_used_monotonic: float
    mod_id: Optional[str] = None


class MultiDbConsistencyManager:
    """线程安全的 "URL → engine/session" 集中池,主 + 各 Mod 副本共享同一把锁。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._engines: dict[str, _CachedBinding] = {}
        self._write_locks: dict[str, threading.RLock] = {}
        self._active_mod_index: dict[str, str] = {}  # logical_key -> last mod_id
        self._sqlite_desktop = (
            (os.environ.get("XCAGI_DESKTOP_MODE") or "").strip().lower()
            in {"1", "true", "yes", "on"}
        )

    # ............................................................ URL 入口

    def resolve_canonical(self, url: str) -> str:
        """公共入口:把任何 URL 折成规范 key(测试/外层也可以用)。"""
        return canonicalize_database_url(url)

    # ............................................................ engine 池

    def get_engine(
        self,
        url: str,
        *,
        mod_id: Optional[str] = None,
        creator: Optional[Any] = None,
    ) -> Engine:
        """原子地 "解析 URL + 创建/复用 engine",加锁确保两个线程同一 URL 只 new 一次。"""
        key = self.resolve_canonical(url)
        with self._lock:
            cached = self._engines.get(key)
            if cached is not None:
                cached.last_used_monotonic = _now()
                cached.mod_id = mod_id
                self._active_mod_index[key] = mod_id or ""
                return cached.engine
            engine = (creator or self._default_creator)(url) if creator else self._default_creator(url)
            session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            self._engines[key] = _CachedBinding(
                engine=engine,
                session_factory=session_factory,
                last_used_monotonic=_now(),
                mod_id=mod_id,
            )
            self._active_mod_index[key] = mod_id or ""
            return engine

    def get_session_factory(self, url: str, *, mod_id: Optional[str] = None) -> sessionmaker:
        """原子地 "解析 URL + 复用 sessionmaker",与 ``get_engine`` 走同一把锁。"""
        key = self.resolve_canonical(url)
        with self._lock:
            cached = self._engines.get(key)
            if cached is None:
                # 没建过 engine → 触发默认建库路径
                self.get_engine(url, mod_id=mod_id)
                cached = self._engines[key]
            cached.last_used_monotonic = _now()
            cached.mod_id = mod_id
            self._active_mod_index[key] = mod_id or ""
            return cached.session_factory

    # ............................................................ 写并发

    def write_lock_for(self, url: str) -> threading.RLock:
        """返回 per-DB 写锁;SQLite 桌面/服务全场景使用,保证 ``database is locked`` 不会再出现。"""
        key = self.resolve_canonical(url)
        with self._lock:
            lock = self._write_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._write_locks[key] = lock
            return lock

    @contextmanager
    def transaction(self, url: str, *, mod_id: Optional[str] = None) -> Iterator[Session]:
        """统一事务上下文:取 session → 写锁内 commit/rollback → 关 session。

        用法::

            with manager.transaction(url, mod_id="erp") as db:
                db.add(...)
        """
        factory = self.get_session_factory(url, mod_id=mod_id)
        session = factory()
        try:
            with self.write_lock_for(url):
                yield session
                session.commit()
        except Exception:
            try:
                session.rollback()
            except Exception:  # pragma: no cover - rollback best-effort
                logger.exception("rollback failed")
            raise
        finally:
            try:
                session.close()
            except Exception:  # pragma: no cover - close best-effort
                logger.exception("session.close failed")

    # ............................................................ 失效

    def invalidate(self, url: Optional[str] = None) -> None:
        """失效一个 URL 的缓存;``url=None`` 时清空所有。"""
        with self._lock:
            if url is None:
                keys = list(self._engines.keys())
            else:
                key = self.resolve_canonical(url)
                keys = [key] if key in self._engines else []
            for key in keys:
                binding = self._engines.pop(key, None)
                if binding is not None:
                    try:
                        binding.engine.dispose()
                    except Exception:  # pragma: no cover - dispose best-effort
                        logger.exception("engine.dispose failed for %s", key)
                self._active_mod_index.pop(key, None)
                # 写锁保留:同一文件后续还要写,锁自身可重入

    def dispose_all(self) -> None:
        """测试 / 重载场景下一键释放所有 engine。"""
        with self._lock:
            for binding in self._engines.values():
                try:
                    binding.engine.dispose()
                except Exception:  # pragma: no cover
                    logger.exception("engine.dispose failed during dispose_all")
            self._engines.clear()
            self._active_mod_index.clear()
            # _write_locks 也清空,防止"已 dispose 的 URL 锁"残留指向新 key
            self._write_locks.clear()

    # ............................................................ 内部

    def _default_creator(self, url: str) -> Engine:
        """根据 URL 类型选 StaticPool / NullPool,保持与 ``app.db._create_engine_for_url`` 一致。"""
        from sqlalchemy import create_engine

        if url.startswith("sqlite"):
            if self._sqlite_desktop:
                return create_engine(
                    url,
                    connect_args={"check_same_thread": False, "timeout": 45},
                    poolclass=StaticPool,
                    echo=False,
                )
            return create_engine(
                url,
                connect_args={"check_same_thread": False, "timeout": 45},
                poolclass=NullPool,
                echo=False,
            )
        connect_args = {"connect_timeout": int(os.environ.get("PGCONNECT_TIMEOUT", "5"))}
        return create_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=3600,
            pool_timeout=30,
            echo=False,
        )


def _now() -> float:
    import time

    return time.monotonic()


# ............................................................ 进程级单例


_MANAGER: MultiDbConsistencyManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_consistency_manager() -> MultiDbConsistencyManager:
    """返回进程级单例;首次调用时初始化。"""
    global _MANAGER
    if _MANAGER is not None:
        return _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = MultiDbConsistencyManager()
        return _MANAGER


def reset_consistency_manager() -> None:
    """测试用:重置单例(配 ``dispose_all``)。"""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is not None:
            _MANAGER.dispose_all()
        _MANAGER = None


__all__ = [
    "MultiDbConsistencyManager",
    "canonicalize_database_url",
    "get_consistency_manager",
    "reset_consistency_manager",
]
