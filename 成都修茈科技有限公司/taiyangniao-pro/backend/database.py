"""
太阳鸟pro - 数据库连接和会话管理
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.workspace import workspace_root

try:
    from .models import Base
except ImportError:
    try:
        from models import Base
    except ImportError:
        Base = None  # type: ignore[misc,assignment]

# 默认数据库文件名
DEFAULT_DB_NAME = "taiyangniao_pro.db"


def get_database_path() -> Path:
    """获取 mod 业务库 ``taiyangniao_pro.db`` 路径。

    与 ``app.infrastructure.workspace`` 一致：默认 ``WORKSPACE_ROOT``（未设则为进程 cwd），
    可用 ``XCAGI_WORKSPACE_ROOT`` 覆盖。避免在路由里写死盘符，否则换目录启动会连到空库。
    """
    wr = (os.environ.get("XCAGI_WORKSPACE_ROOT") or "").strip()
    base_path = Path(wr).resolve() if wr else workspace_root()

    # 在 workspace 下创建数据库目录
    db_dir = base_path / "data" / "mod_dbs"
    db_dir.mkdir(parents=True, exist_ok=True)

    return db_dir / DEFAULT_DB_NAME


def get_engine():
    """创建数据库引擎"""
    db_path = get_database_path()
    # SQLite连接字符串
    connection_string = f"sqlite:///{db_path}"
    return create_engine(connection_string, connect_args={"check_same_thread": False})


def init_database():
    """初始化数据库，创建所有表"""
    if Base is None:
        raise RuntimeError(
            "taiyangniao-pro: 缺少 backend/models.py（或无法导入 Base），无法 init_database。"
        )
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    return engine


# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False)


def get_session() -> Generator[Session, None, None]:
    """获取数据库会话的生成器，用于依赖注入"""
    engine = get_engine()
    SessionLocal.configure(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_session_context() -> Session:
    """获取数据库会话的上下文管理器"""
    engine = get_engine()
    SessionLocal.configure(bind=engine)
    return SessionLocal()
