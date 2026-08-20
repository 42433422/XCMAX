# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.db.init_db")


def _orm_table(model: _facade().Any) -> _facade().Table:
    """Narrow SQLAlchemy's declarative ``__table__`` to its runtime type."""
    return _facade().cast("Table", model.__table__)


def _is_desktop_mode_env() -> bool:
    return (
        _facade().os.environ.get("XCAGI_DESKTOP_MODE") or ""
    ).strip().lower() in _facade()._TRUTHY_ENV_VALUES


def refresh_config_database_urls(config: _facade().Any | None = None) -> None:
    """Refresh database URL fields on a Config-like object from current environment."""
    if config is None:
        return
    for attr, env_name in (
        ("DATABASE_URL", "DATABASE_URL"),
        ("VECTOR_DB_URL", "VECTOR_DB_URL"),
        ("DATABASE_PATH", "DATABASE_PATH"),
    ):
        value = _facade().os.environ.get(env_name)
        if value:
            setattr(config, attr, value)


def _desktop_data_root(data_dir: str | None = None) -> _facade().Path:
    raw = data_dir or _facade().os.environ.get("XCAGI_DATA_DIR") or _facade().get_app_data_dir()
    return _facade().Path(raw).expanduser()


def _ensure_sqlite_business_tables(db_path: _facade().Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _facade().sqlite3.connect(db_path) as conn:
        conn.execute(
            "\n            CREATE TABLE IF NOT EXISTS purchase_units (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                unit_name TEXT NOT NULL DEFAULT '',\n                contact_person TEXT,\n                contact_phone TEXT,\n                address TEXT,\n                is_active BOOLEAN DEFAULT 1,\n                tenant_id INTEGER,\n                unit_code TEXT NOT NULL DEFAULT '',\n                created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n                updated_at TEXT DEFAULT CURRENT_TIMESTAMP\n            )\n            "
        )
        conn.execute(
            "\n            CREATE TABLE IF NOT EXISTS products (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                name TEXT NOT NULL DEFAULT '',\n                model_number TEXT NOT NULL DEFAULT '',\n                unit TEXT NOT NULL DEFAULT '',\n                purchase_unit_id INTEGER,\n                tenant_id INTEGER,\n                created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n                updated_at TEXT DEFAULT CURRENT_TIMESTAMP\n            )\n            "
        )
        conn.commit()


def ensure_desktop_sqlite_business_tables_all_files(data_dir: str | None = None) -> None:
    """Ensure desktop SQLite databases have the business tables needed at startup."""
    root = _facade()._desktop_data_root(data_dir)
    data_root = root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    candidates = {path for path in data_root.glob("*.db") if path.is_file()}
    candidates.update(path for path in root.glob("*.db") if path.is_file())
    if not candidates:
        candidates.add(data_root / "xcagi.db")
    for db_path in sorted(candidates):
        _facade()._ensure_sqlite_business_tables(db_path)


def ensure_runtime_database_environment() -> str:
    """Select the runtime database URL, forcing desktop mode onto local SQLite."""
    if _facade()._is_desktop_mode_env():
        root = _facade()._desktop_data_root()
        data_root = root / "data"
        db_path = data_root / "xcagi.db"
        url = f"sqlite:///{db_path}"
        data_root.mkdir(parents=True, exist_ok=True)
        _facade().os.environ["DATABASE_URL"] = url
        _facade().os.environ["DATABASE_PATH"] = str(data_root)
        _facade().ensure_desktop_sqlite_business_tables_all_files(str(root))
        try:
            from app.config import Config

            _facade().refresh_config_database_urls(Config)
        except _facade().RECOVERABLE_ERRORS:
            pass
        return url
    return _facade().os.environ.get("DATABASE_URL", "")


def _iter_seed_dirs() -> _facade().Iterable[str]:
    """
    返回可能的种子 db 来源目录（按优先级）。
    - resources/db_seed（推荐）
    - base_dir（兼容旧行为）
    - _MEIPASS（打包时解包目录）
    """
    yield _facade().get_resource_path("db_seed")
    yield _facade().get_base_dir()
    if hasattr(_facade().sys, "_MEIPASS"):
        yield _facade().sys._MEIPASS


def initialize_databases(db_files: _facade().Iterable[str] = _facade().DEFAULT_DB_FILES) -> None:
    """
    初始化数据库文件（主要用于首次运行/打包环境）。
    规则：如果目标目录已存在同名 db，则不覆盖。
    """
    work_dir = _facade().get_app_data_dir()
    _facade().os.makedirs(work_dir, exist_ok=True)
    for db_file in db_files:
        target_path = _facade().os.path.join(work_dir, db_file)
        if _facade().os.path.exists(target_path):
            continue
        source_path = None
        for seed_dir in _facade()._iter_seed_dirs():
            cand = _facade().os.path.join(seed_dir, db_file)
            if _facade().os.path.exists(cand):
                source_path = cand
                break
        if not source_path:
            _facade().logger.warning("未找到种子数据库文件：%s（将由 ORM/运行时创建）", db_file)
            continue
        try:
            _facade().shutil.copy2(source_path, target_path)
            with _facade().sqlite_conn(target_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                _ = cur.fetchall()
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.warning("复制数据库失败 %s -> %s: %s", source_path, target_path, e)


def ensure_sqlite_per_mod_database_copies(
    mod_ids: _facade().Sequence[str], db_files: _facade().Iterable[str] = _facade().DEFAULT_DB_FILES
) -> None:
    """
    为每个扩展从「母库」复制出带 Mod 后缀的 SQLite 文件（若目标尚不存在）。

    母库即数据目录下无后缀的 ``products.db`` 等（由 ``initialize_databases`` 从
    ``resources/db_seed`` 首次复制而来）。这样 ``DATABASE_URL`` 按请求头改写为
    ``products__<mod>.db`` 时，各包有独立文件，不会在空文件上直接建表导致与母库「串数据」。
    """
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix

    work_dir = _facade().get_app_data_dir()
    _facade().os.makedirs(work_dir, exist_ok=True)
    seen: set[str] = set()
    for raw_id in mod_ids:
        mod_id = str(raw_id or "").strip()
        if not mod_id or mod_id in seen:
            continue
        seen.add(mod_id)
        for db_name in db_files:
            base_path = _facade().os.path.join(work_dir, db_name)
            dest_name = sqlite_filename_with_mod_suffix(db_name, mod_id)
            dest_path = _facade().os.path.join(work_dir, dest_name)
            if dest_name == db_name or _facade().os.path.exists(dest_path):
                continue
            if not _facade().os.path.exists(base_path):
                _facade().logger.warning(
                    "无法为 Mod %s 准备专用库：母库不存在 %s（跳过 %s）",
                    mod_id,
                    base_path,
                    dest_name,
                )
                continue
            try:
                _facade().shutil.copy2(base_path, dest_path)
                _facade().logger.info("已为 Mod %s 从母库复制专用 SQLite：%s", mod_id, dest_name)
            except _facade().RECOVERABLE_ERRORS as e:
                _facade().logger.warning(
                    "复制 Mod 专用库失败 mod=%s %s -> %s: %s", mod_id, base_path, dest_path, e
                )


def build_mod_database_seed_plan() -> dict[str, _facade().Any]:
    """
    供设置页 ``/api/system/test-db/status`` 展示：各扩展对应的 SQLite 文件路径与说明。
    与 manifest 可选字段 ``database.seed_files`` / ``database.notes_zh`` 对齐（若存在）。
    """
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix

    work_dir = _facade().get_app_data_dir()
    architecture_note_zh = "SQLite：先有母库（如 products.db，来自 resources/db_seed），每个扩展使用独立文件名（如 products__<mod>.db）；启动时若专用文件不存在，会从母库复制一份作为初始种子，之后各包数据互不影响。PostgreSQL 默认仍共用 DATABASE_URL 中的库；需要一包一库时请设置 XCAGI_MOD_ISOLATED_DATABASES=1 或为各包配置 XCAGI_MOD_DATABASE_URL_*。"
    mods_out: list[dict[str, _facade().Any]] = []
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mm = get_mod_manager()
        metas = mm.list_loaded_mods() or mm.scan_mods()
    except _facade().RECOVERABLE_ERRORS:
        metas = []
    for m in metas:
        mid = str(getattr(m, "id", "") or "").strip()
        if not mid:
            continue
        notes = ""
        extra_seeds: list[dict[str, str]] = []
        mod_path = str(getattr(m, "mod_path", "") or "").strip()
        if mod_path:
            man = _facade().os.path.join(mod_path, "manifest.json")
            if _facade().os.path.isfile(man):
                try:
                    with open(man, encoding="utf-8") as fh:
                        data = _facade().json.load(fh)
                    db = data.get("database") if isinstance(data.get("database"), dict) else {}
                    notes = str(db.get("notes_zh") or data.get("database_notes_zh") or "").strip()
                    raw_files = db.get("seed_files") or data.get("database_seed_files") or []
                    if isinstance(raw_files, list):
                        for rel in raw_files:
                            rp = str(rel or "").strip()
                            if not rp:
                                continue
                            ap = _facade().os.path.normpath(_facade().os.path.join(mod_path, rp))
                            extra_seeds.append({"path": ap})
                    raw_sql = db.get("seed_sql") or data.get("database_seed_sql")
                    if raw_sql:
                        sp = _facade().os.path.normpath(
                            _facade().os.path.join(mod_path, str(raw_sql).strip())
                        )
                        if _facade().os.path.isfile(sp):
                            extra_seeds.append({"path": sp})
                except _facade().RECOVERABLE_ERRORS:
                    pass
        seeds: list[dict[str, str]] = [
            {
                "path": _facade().os.path.join(work_dir, "products.db"),
                "role": "sqlite_mother_products",
            },
            {
                "path": _facade().os.path.join(
                    work_dir, sqlite_filename_with_mod_suffix("products.db", mid)
                ),
                "role": "sqlite_per_mod_products",
            },
        ]
        seeds.extend(extra_seeds)
        mods_out.append({"mod_id": mid, "database_notes": notes, "seeds": seeds})
    return {"architecture_note_zh": architecture_note_zh, "mods": mods_out}


def get_db_path(db_name: str = "products.db") -> str:
    """
    获取主数据库（或指定 db）路径。

    当请求上下文存在 ``X-XCAGI-Active-Mod-Id``（SQLite 场景）时，与 ORM 的
    ``DATABASE_URL`` 改写一致，使用带 Mod 后缀的文件名（如 ``products__taiyangniao_pro.db``）。
    """
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix
    from app.request_active_mod_ctx import get_request_active_mod_id

    mod_id = get_request_active_mod_id()
    fname = sqlite_filename_with_mod_suffix(db_name, mod_id) if mod_id else db_name
    return _facade().os.path.join(_facade().get_app_data_dir(), fname)


def get_distillation_db_path() -> str:
    return _facade().get_db_path("distillation.db")


def init_distillation_tables(engine: _facade().Engine) -> None:
    """
    在主库上创建蒸馏样本表 distillation_log / training_stats。
    与 SessionLocal 使用同一引擎，避免切换 SQLite/PostgreSQL 后路由与采集脚本连库不一致。
    """
    from sqlalchemy import text

    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(
                text(
                    "\n                    CREATE TABLE IF NOT EXISTS distillation_log (\n                        id INTEGER PRIMARY KEY AUTOINCREMENT,\n                        query TEXT NOT NULL,\n                        intent TEXT NOT NULL,\n                        slots TEXT,\n                        confidence REAL DEFAULT 1.0,\n                        source TEXT DEFAULT 'manual',\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n                        used_for_training INTEGER DEFAULT 0\n                    )\n                    "
                )
            )
            conn.execute(
                text(
                    "\n                    CREATE TABLE IF NOT EXISTS training_stats (\n                        id INTEGER PRIMARY KEY AUTOINCREMENT,\n                        intent TEXT NOT NULL,\n                        count INTEGER DEFAULT 0,\n                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    "
                )
            )
        else:
            conn.execute(
                text(
                    "\n                    CREATE TABLE IF NOT EXISTS distillation_log (\n                        id BIGSERIAL PRIMARY KEY,\n                        query TEXT NOT NULL,\n                        intent TEXT NOT NULL,\n                        slots TEXT,\n                        confidence DOUBLE PRECISION DEFAULT 1.0,\n                        source TEXT DEFAULT 'manual',\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n                        used_for_training INTEGER DEFAULT 0\n                    )\n                    "
                )
            )
            conn.execute(
                text(
                    "\n                    CREATE TABLE IF NOT EXISTS training_stats (\n                        id BIGSERIAL PRIMARY KEY,\n                        intent TEXT NOT NULL,\n                        count INTEGER DEFAULT 0,\n                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    "
                )
            )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_intent ON distillation_log(intent)"))
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_used ON distillation_log(used_for_training)")
        )


def init_extract_logs_tables(engine: _facade().Engine) -> None:
    """
    在主库上创建 extract_logs（与 SessionLocal / pytest 临时 SQLite 使用同一引擎）。
    ExtractLog 仓储使用原生 SQL，需显式建表。
    """
    from sqlalchemy import text

    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(
                text(
                    "\n                    CREATE TABLE IF NOT EXISTS extract_logs (\n                        id INTEGER PRIMARY KEY AUTOINCREMENT,\n                        file_name TEXT,\n                        file_path TEXT,\n                        data_type TEXT,\n                        total_rows INTEGER DEFAULT 0,\n                        valid_rows INTEGER,\n                        imported_rows INTEGER,\n                        skipped_rows INTEGER,\n                        failed_rows INTEGER,\n                        status TEXT DEFAULT 'pending',\n                        error_message TEXT,\n                        field_mapping TEXT,\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    "
                )
            )
        else:
            conn.execute(
                text(
                    "\n                    CREATE TABLE IF NOT EXISTS extract_logs (\n                        id BIGSERIAL PRIMARY KEY,\n                        file_name TEXT,\n                        file_path TEXT,\n                        data_type TEXT,\n                        total_rows INTEGER DEFAULT 0,\n                        valid_rows INTEGER,\n                        imported_rows INTEGER,\n                        skipped_rows INTEGER,\n                        failed_rows INTEGER,\n                        status TEXT DEFAULT 'pending',\n                        error_message TEXT,\n                        field_mapping TEXT,\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    "
                )
            )
