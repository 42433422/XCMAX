"""跨行业通用考勤模块数据库连接（Mod 私有 SQLite，与主库拆分并存）。"""

from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.mod_sdk.owner_workspace import attendance_database_path

try:
    from .models import Base
except ImportError:
    try:
        from models import Base
    except ImportError:
        Base = None  # type: ignore[misc,assignment]


def get_database_path():
    """当前已登录 owner 的业务库；不自动接管历史无归属侧库。"""
    return attendance_database_path()


def get_engine():
    """Bind each requested session to the current authenticated owner."""
    db_path = get_database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 45},
        poolclass=NullPool,
        echo=False,
    )


def init_database():
    """初始化数据库，创建所有表"""
    if Base is None:
        raise RuntimeError(
            "attendance-industry: 缺少 backend/models.py（或无法导入 Base），无法 init_database。"
        )
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    return engine


def _sessionmaker() -> sessionmaker:
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def get_session() -> Generator[Session, None, None]:
    """获取数据库会话的生成器，用于依赖注入"""
    session = _sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def get_session_context() -> Session:
    """获取数据库会话（调用方负责 close）。"""
    return _sessionmaker()()
