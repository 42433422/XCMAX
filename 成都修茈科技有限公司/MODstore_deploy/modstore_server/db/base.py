"""引擎、会话、元数据 Base 以及 ``init_db`` 迁移钩子。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

__all__ = [
    "Base",
    "_SessionFactory",
    "_add_column_if_missing",
    "_engine",
    "_sqlite_add_column_if_missing",
    "database_url",
    "default_db_path",
    "get_engine",
    "get_session_factory",
    "init_db",
    "init_default_plan_templates",
]


class Base(DeclarativeBase):
    pass


_engine: Optional[Engine] = None
_SessionFactory: Optional[sessionmaker[Session]] = None


def _models_globals() -> tuple[Optional[Engine], Optional[sessionmaker[Session]]]:
    """单测常仅 patch ``modstore_server.models`` 上的全局；与 ``db.base`` 绑分解绑后仍可路由到临时引擎。"""
    try:
        from modstore_server import models as _models

        return getattr(_models, "_engine", None), getattr(_models, "_SessionFactory", None)
    except ImportError:
        return None, None


def default_db_path() -> Path:
    raw = (os.environ.get("MODSTORE_DB_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "modstore.db"


def database_url(db_path: Optional[Path] = None) -> str:
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if raw:
        if raw.startswith("postgres://"):
            return "postgresql://" + raw[len("postgres://") :]
        return raw
    p = db_path or default_db_path()
    return f"sqlite:///{p}"


def get_engine(db_path: Optional[Path] = None) -> Engine:
    global _engine, _SessionFactory
    models_engine, _ = _models_globals()
    if models_engine is not None and models_engine is not _engine:
        return models_engine

    url = database_url(db_path)
    if _engine is not None and str(_engine.url) != url:
        _engine.dispose()
        _engine = None
        _SessionFactory = None

    if _engine is None:
        if url.startswith("sqlite:///"):
            p = Path(url.replace("sqlite:///", "", 1))
            p.parent.mkdir(parents=True, exist_ok=True)
            _engine = create_engine(url, echo=False)
        else:
            _engine = create_engine(
                url,
                echo=False,
                pool_pre_ping=True,
                pool_size=int(os.environ.get("MODSTORE_DB_POOL_SIZE", "10")),
                max_overflow=int(os.environ.get("MODSTORE_DB_MAX_OVERFLOW", "20")),
            )
    return _engine


def get_session_factory(db_path: Optional[Path] = None) -> sessionmaker[Session]:
    global _SessionFactory
    _, models_sf = _models_globals()
    if models_sf is not None and models_sf is not _SessionFactory:
        return models_sf

    if _SessionFactory is None:
        engine = get_engine(db_path)
        _SessionFactory = sessionmaker(bind=engine)
    return _SessionFactory


def _sqlite_add_column_if_missing(engine: Engine, table: str, column: str, ddl_type: str) -> None:
    """SQLite 表结构演进：缺列时 ALTER ADD（幂等）。"""
    with engine.begin() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        if any(row[1] == column for row in rows):
            return
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


def _add_column_if_missing(engine: Engine, table: str, column: str, ddl_type: str) -> None:
    """通用表结构演进：同时支持 SQLite 与 PostgreSQL，缺列时 ALTER ADD（幂等）。"""
    if engine.dialect.name == "sqlite":
        _sqlite_add_column_if_missing(engine, table, column, ddl_type)
        return
    with engine.begin() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        ).first()
        if exists:
            return
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


def init_db(db_path: Optional[Path] = None) -> None:
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    _ensure_columns(engine)
    init_default_plan_templates()


def _ensure_columns(engine: Engine) -> None:
    patches: list[tuple[str, str, str]] = [
        ("workflows", "migration_status", "TEXT DEFAULT ''"),
        ("workflows", "migrated_to_id", "INTEGER"),
        ("workflows", "kind", "TEXT DEFAULT ''"),
        ("users", "is_enterprise", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("daily_digest_records", "vibe_prep_updates_md", "TEXT DEFAULT ''"),
        ("daily_digest_records", "vibe_prep_patches_md", "TEXT DEFAULT ''"),
        ("daily_digest_records", "vibe_prep_meta_json", "TEXT DEFAULT ''"),
        ("daily_digest_records", "vibe_prep_pw_md", "TEXT DEFAULT ''"),
        ("daily_digest_records", "vibe_prep_ps_md", "TEXT DEFAULT ''"),
        ("daily_digest_records", "vibe_prep_app_md", "TEXT DEFAULT ''"),
        ("daily_digest_records", "vibe_prep_sr_md", "TEXT DEFAULT ''"),
        ("daily_digest_records", "vibe_prep_line_dispatch_json", "TEXT DEFAULT ''"),
        ("daily_digest_records", "vibe_line_execute_json", "TEXT DEFAULT ''"),
        ("daily_digest_records", "release_train_before", "TEXT DEFAULT ''"),
        ("daily_digest_records", "release_train_after", "TEXT DEFAULT ''"),
        ("daily_digest_records", "release_kind", "TEXT DEFAULT ''"),
        ("transactions", "idempotency_key", "TEXT DEFAULT ''"),
        ("employee_execution_metrics", "failure_kind", "TEXT DEFAULT ''"),
        ("ai_model_prices", "official_input_price_per_1k", "FLOAT"),
        ("ai_model_prices", "official_output_price_per_1k", "FLOAT"),
        ("ai_model_prices", "official_min_charge", "FLOAT"),
        ("ai_model_prices", "official_source", "VARCHAR(512) DEFAULT ''"),
        ("ai_model_prices", "official_synced_at", "DATETIME"),
    ]
    for table, column, ddl in patches:
        _add_column_if_missing(engine, table, column, ddl)


def init_default_plan_templates() -> None:
    """幂等写入默认会员模板（依赖 :class:`~modstore_server.db.billing.PlanTemplate`）。"""
    from modstore_server.db.billing import PlanTemplate

    defaults: list[dict[str, Any]] = [
        {
            "id": "plan_basic",
            "name": "VIP",
            "description": "入门会员，解锁基础 AI 调用与平台能力",
            "price": 9.90,
            "features_json": '["基础 AI 对话","基础模型额度","可购买更多余额","会员身份标识"]',
            "quotas_json": '{"employee_count":1,"llm_calls":5000,"storage_mb":512}',
        },
        {
            "id": "plan_pro",
            "name": "VIP+",
            "description": "进阶会员，更高额度 + BYOK + 用量明细",
            "price": 29.90,
            "features_json": '["更高 AI 调用额度","BYOK 自有密钥","优先模型接入","用量明细","高级功能优先体验"]',
            "quotas_json": '{"employee_count":3,"llm_calls":30000,"storage_mb":2048}',
        },
        {
            "id": "plan_enterprise",
            "name": "svip",
            "description": "企业级会员（svip），含大额度企业 AI 调用、团队/部署与优先支持",
            "price": 99.90,
            "features_json": '["企业级 AI 调用额度","团队/企业支持","专属部署支持","优先技术支持"]',
            "quotas_json": '{"employee_count":999999,"llm_calls":300000,"storage_mb":10240}',
        },
        {
            "id": "plan_svip2",
            "name": "SVIP2",
            "description": "SVIP 进阶档（需已是 SVIP 用户）",
            "price": 199.00,
            "features_json": '["svip 全部权益","双倍 AI 调用额度","专属客服群组","新功能内测资格"]',
            "quotas_json": '{"employee_count":999999,"llm_calls":600000,"storage_mb":20480}',
        },
        {
            "id": "plan_svip3",
            "name": "SVIP3",
            "description": "SVIP 进阶档（需已是 SVIP 用户）",
            "price": 299.00,
            "features_json": '["SVIP2 全部权益","三倍 AI 调用额度","定制工作流模板"]',
            "quotas_json": '{"employee_count":999999,"llm_calls":900000,"storage_mb":30720}',
        },
        {
            "id": "plan_svip4",
            "name": "SVIP4",
            "description": "SVIP 进阶档（需已是 SVIP 用户）",
            "price": 499.00,
            "features_json": '["SVIP3 全部权益","五倍 AI 调用额度","专家咨询时长 2h/月"]',
            "quotas_json": '{"employee_count":999999,"llm_calls":1500000,"storage_mb":51200}',
        },
        {
            "id": "plan_svip5",
            "name": "SVIP5",
            "description": "SVIP 进阶档（需已是 SVIP 用户）",
            "price": 999.00,
            "features_json": '["SVIP4 全部权益","十倍 AI 调用额度","专家咨询时长 5h/月"]',
            "quotas_json": '{"employee_count":999999,"llm_calls":3000000,"storage_mb":102400}',
        },
        {
            "id": "plan_svip6",
            "name": "SVIP6",
            "description": "SVIP 进阶档（需已是 SVIP 用户）",
            "price": 1999.00,
            "features_json": '["SVIP5 全部权益","二十倍 AI 调用额度","驻场技术对接 1d/月"]',
            "quotas_json": '{"employee_count":999999,"llm_calls":6000000,"storage_mb":204800}',
        },
        {
            "id": "plan_svip7",
            "name": "SVIP7",
            "description": "SVIP 进阶档（需已是 SVIP 用户）",
            "price": 2999.00,
            "features_json": '["SVIP6 全部权益","三十倍 AI 调用额度","驻场技术对接 2d/月","品牌联合露出"]',
            "quotas_json": '{"employee_count":999999,"llm_calls":9000000,"storage_mb":307200}',
        },
        {
            "id": "plan_svip8",
            "name": "SVIP8",
            "description": "SVIP 顶级档（需已是 SVIP 用户）",
            "price": 4999.00,
            "features_json": '["SVIP7 全部权益","无限 AI 调用额度","驻场技术对接 5d/月","战略合作通道"]',
            "quotas_json": '{"employee_count":999999,"llm_calls":99999999,"storage_mb":1048576}',
        },
    ]
    sf = get_session_factory()
    with sf() as session:
        for row in defaults:
            exists = session.query(PlanTemplate).filter(PlanTemplate.id == row["id"]).first()
            if exists:
                exists.name = row["name"]
                exists.description = row["description"]
                exists.features_json = row["features_json"]
                exists.quotas_json = row["quotas_json"]
                exists.price = row["price"]
                exists.is_active = True
                continue
            session.add(PlanTemplate(**row))
        session.commit()
