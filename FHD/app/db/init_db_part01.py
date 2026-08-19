# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib
from sqlalchemy import Table
from sqlalchemy.engine import Engine

def _facade():
    return importlib.import_module('app.db.init_db')

def _orm_table(model: _facade().Any) -> Table:
    """Narrow SQLAlchemy's declarative ``__table__`` to its runtime type."""
    return _facade().cast('Table', model.__table__)

def _is_desktop_mode_env() -> bool:
    return (_facade().os.environ.get('XCAGI_DESKTOP_MODE') or '').strip().lower() in _facade()._TRUTHY_ENV_VALUES

def refresh_config_database_urls(config: _facade().Any | None=None) -> None:
    """Refresh database URL fields on a Config-like object from current environment."""
    if config is None:
        return
    for (attr, env_name) in (('DATABASE_URL', 'DATABASE_URL'), ('VECTOR_DB_URL', 'VECTOR_DB_URL'), ('DATABASE_PATH', 'DATABASE_PATH')):
        value = _facade().os.environ.get(env_name)
        if value:
            setattr(config, attr, value)

def _desktop_data_root(data_dir: str | None=None) -> _facade().Path:
    raw = data_dir or _facade().os.environ.get('XCAGI_DATA_DIR') or _facade().get_app_data_dir()
    return _facade().Path(raw).expanduser()

def _ensure_sqlite_business_tables(db_path: _facade().Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _facade().sqlite3.connect(db_path) as conn:
        conn.execute("\n            CREATE TABLE IF NOT EXISTS purchase_units (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                unit_name TEXT NOT NULL DEFAULT '',\n                contact_person TEXT,\n                contact_phone TEXT,\n                address TEXT,\n                is_active BOOLEAN DEFAULT 1,\n                tenant_id INTEGER,\n                unit_code TEXT NOT NULL DEFAULT '',\n                created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n                updated_at TEXT DEFAULT CURRENT_TIMESTAMP\n            )\n            ")
        conn.execute("\n            CREATE TABLE IF NOT EXISTS products (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                name TEXT NOT NULL DEFAULT '',\n                model_number TEXT NOT NULL DEFAULT '',\n                unit TEXT NOT NULL DEFAULT '',\n                purchase_unit_id INTEGER,\n                tenant_id INTEGER,\n                created_at TEXT DEFAULT CURRENT_TIMESTAMP,\n                updated_at TEXT DEFAULT CURRENT_TIMESTAMP\n            )\n            ")
        conn.commit()

def ensure_desktop_sqlite_business_tables_all_files(data_dir: str | None=None) -> None:
    """Ensure desktop SQLite databases have the business tables needed at startup."""
    root = _facade()._desktop_data_root(data_dir)
    data_root = root / 'data'
    data_root.mkdir(parents=True, exist_ok=True)
    candidates = {path for path in data_root.glob('*.db') if path.is_file()}
    candidates.update((path for path in root.glob('*.db') if path.is_file()))
    if not candidates:
        candidates.add(data_root / 'xcagi.db')
    for db_path in sorted(candidates):
        _facade()._ensure_sqlite_business_tables(db_path)

def ensure_runtime_database_environment() -> str:
    """Select the runtime database URL, forcing desktop mode onto local SQLite."""
    if _facade()._is_desktop_mode_env():
        root = _facade()._desktop_data_root()
        data_root = root / 'data'
        db_path = data_root / 'xcagi.db'
        url = f'sqlite:///{db_path}'
        data_root.mkdir(parents=True, exist_ok=True)
        _facade().os.environ['DATABASE_URL'] = url
        _facade().os.environ['DATABASE_PATH'] = str(data_root)
        _facade().ensure_desktop_sqlite_business_tables_all_files(str(root))
        try:
            from app.config import Config
            _facade().refresh_config_database_urls(Config)
        except _facade().RECOVERABLE_ERRORS:
            pass
        return url
    return _facade().os.environ.get('DATABASE_URL', '')

def _iter_seed_dirs() -> _facade().Iterable[str]:
    """
    返回可能的种子 db 来源目录（按优先级）。
    - resources/db_seed（推荐）
    - base_dir（兼容旧行为）
    - _MEIPASS（打包时解包目录）
    """
    yield _facade().get_resource_path('db_seed')
    yield _facade().get_base_dir()
    if hasattr(_facade().sys, '_MEIPASS'):
        yield _facade().sys._MEIPASS

def initialize_databases(db_files: _facade().Iterable[str]=_facade().DEFAULT_DB_FILES) -> None:
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
            _facade().logger.warning('未找到种子数据库文件：%s（将由 ORM/运行时创建）', db_file)
            continue
        try:
            _facade().shutil.copy2(source_path, target_path)
            with _facade().sqlite_conn(target_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                _ = cur.fetchall()
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.warning('复制数据库失败 %s -> %s: %s', source_path, target_path, e)

def ensure_sqlite_per_mod_database_copies(mod_ids: _facade().Sequence[str], db_files: _facade().Iterable[str]=_facade().DEFAULT_DB_FILES) -> None:
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
        mod_id = str(raw_id or '').strip()
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
                _facade().logger.warning('无法为 Mod %s 准备专用库：母库不存在 %s（跳过 %s）', mod_id, base_path, dest_name)
                continue
            try:
                _facade().shutil.copy2(base_path, dest_path)
                _facade().logger.info('已为 Mod %s 从母库复制专用 SQLite：%s', mod_id, dest_name)
            except _facade().RECOVERABLE_ERRORS as e:
                _facade().logger.warning('复制 Mod 专用库失败 mod=%s %s -> %s: %s', mod_id, base_path, dest_path, e)

def build_mod_database_seed_plan() -> dict[str, _facade().Any]:
    """
    供设置页 ``/api/system/test-db/status`` 展示：各扩展对应的 SQLite 文件路径与说明。
    与 manifest 可选字段 ``database.seed_files`` / ``database.notes_zh`` 对齐（若存在）。
    """
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix
    work_dir = _facade().get_app_data_dir()
    architecture_note_zh = 'SQLite：先有母库（如 products.db，来自 resources/db_seed），每个扩展使用独立文件名（如 products__<mod>.db）；启动时若专用文件不存在，会从母库复制一份作为初始种子，之后各包数据互不影响。PostgreSQL 默认仍共用 DATABASE_URL 中的库；需要一包一库时请设置 XCAGI_MOD_ISOLATED_DATABASES=1 或为各包配置 XCAGI_MOD_DATABASE_URL_*。'
    mods_out: list[dict[str, _facade().Any]] = []
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager
        mm = get_mod_manager()
        metas = mm.list_loaded_mods() or mm.scan_mods()
    except _facade().RECOVERABLE_ERRORS:
        metas = []
    for m in metas:
        mid = str(getattr(m, 'id', '') or '').strip()
        if not mid:
            continue
        notes = ''
        extra_seeds: list[dict[str, str]] = []
        mod_path = str(getattr(m, 'mod_path', '') or '').strip()
        if mod_path:
            man = _facade().os.path.join(mod_path, 'manifest.json')
            if _facade().os.path.isfile(man):
                try:
                    with open(man, encoding='utf-8') as fh:
                        data = _facade().json.load(fh)
                    db = data.get('database') if isinstance(data.get('database'), dict) else {}
                    notes = str(db.get('notes_zh') or data.get('database_notes_zh') or '').strip()
                    raw_files = db.get('seed_files') or data.get('database_seed_files') or []
                    if isinstance(raw_files, list):
                        for rel in raw_files:
                            rp = str(rel or '').strip()
                            if not rp:
                                continue
                            ap = _facade().os.path.normpath(_facade().os.path.join(mod_path, rp))
                            extra_seeds.append({'path': ap})
                    raw_sql = db.get('seed_sql') or data.get('database_seed_sql')
                    if raw_sql:
                        sp = _facade().os.path.normpath(_facade().os.path.join(mod_path, str(raw_sql).strip()))
                        if _facade().os.path.isfile(sp):
                            extra_seeds.append({'path': sp})
                except _facade().RECOVERABLE_ERRORS:
                    pass
        seeds: list[dict[str, str]] = [{'path': _facade().os.path.join(work_dir, 'products.db'), 'role': 'sqlite_mother_products'}, {'path': _facade().os.path.join(work_dir, sqlite_filename_with_mod_suffix('products.db', mid)), 'role': 'sqlite_per_mod_products'}]
        seeds.extend(extra_seeds)
        mods_out.append({'mod_id': mid, 'database_notes': notes, 'seeds': seeds})
    return {'architecture_note_zh': architecture_note_zh, 'mods': mods_out}

def get_db_path(db_name: str='products.db') -> str:
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
    return _facade().get_db_path('distillation.db')

def init_distillation_tables(engine: Engine) -> None:
    """
    在主库上创建蒸馏样本表 distillation_log / training_stats。
    与 SessionLocal 使用同一引擎，避免切换 SQLite/PostgreSQL 后路由与采集脚本连库不一致。
    """
    from sqlalchemy import text
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == 'sqlite':
            conn.execute(text("\n                    CREATE TABLE IF NOT EXISTS distillation_log (\n                        id INTEGER PRIMARY KEY AUTOINCREMENT,\n                        query TEXT NOT NULL,\n                        intent TEXT NOT NULL,\n                        slots TEXT,\n                        confidence REAL DEFAULT 1.0,\n                        source TEXT DEFAULT 'manual',\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n                        used_for_training INTEGER DEFAULT 0\n                    )\n                    "))
            conn.execute(text('\n                    CREATE TABLE IF NOT EXISTS training_stats (\n                        id INTEGER PRIMARY KEY AUTOINCREMENT,\n                        intent TEXT NOT NULL,\n                        count INTEGER DEFAULT 0,\n                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    '))
        else:
            conn.execute(text("\n                    CREATE TABLE IF NOT EXISTS distillation_log (\n                        id BIGSERIAL PRIMARY KEY,\n                        query TEXT NOT NULL,\n                        intent TEXT NOT NULL,\n                        slots TEXT,\n                        confidence DOUBLE PRECISION DEFAULT 1.0,\n                        source TEXT DEFAULT 'manual',\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n                        used_for_training INTEGER DEFAULT 0\n                    )\n                    "))
            conn.execute(text('\n                    CREATE TABLE IF NOT EXISTS training_stats (\n                        id BIGSERIAL PRIMARY KEY,\n                        intent TEXT NOT NULL,\n                        count INTEGER DEFAULT 0,\n                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    '))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_intent ON distillation_log(intent)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_used ON distillation_log(used_for_training)'))

def init_extract_logs_tables(engine: Engine) -> None:
    """
    在主库上创建 extract_logs（与 SessionLocal / pytest 临时 SQLite 使用同一引擎）。
    ExtractLog 仓储使用原生 SQL，需显式建表。
    """
    from sqlalchemy import text
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == 'sqlite':
            conn.execute(text("\n                    CREATE TABLE IF NOT EXISTS extract_logs (\n                        id INTEGER PRIMARY KEY AUTOINCREMENT,\n                        file_name TEXT,\n                        file_path TEXT,\n                        data_type TEXT,\n                        total_rows INTEGER DEFAULT 0,\n                        valid_rows INTEGER,\n                        imported_rows INTEGER,\n                        skipped_rows INTEGER,\n                        failed_rows INTEGER,\n                        status TEXT DEFAULT 'pending',\n                        error_message TEXT,\n                        field_mapping TEXT,\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    "))
        else:
            conn.execute(text("\n                    CREATE TABLE IF NOT EXISTS extract_logs (\n                        id BIGSERIAL PRIMARY KEY,\n                        file_name TEXT,\n                        file_path TEXT,\n                        data_type TEXT,\n                        total_rows INTEGER DEFAULT 0,\n                        valid_rows INTEGER,\n                        imported_rows INTEGER,\n                        skipped_rows INTEGER,\n                        failed_rows INTEGER,\n                        status TEXT DEFAULT 'pending',\n                        error_message TEXT,\n                        field_mapping TEXT,\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    "))

def init_template_tables(db_path: str | None=None) -> None:
    """
    初始化模板相关表：
    - templates
    - template_usage_log

    兼容策略：
    - 表不存在时创建
    - 表已存在但缺少新字段时自动补齐
    """
    db_path = db_path or _facade().get_db_path('products.db')
    with _facade().sqlite_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute('\n            CREATE TABLE IF NOT EXISTS templates (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                template_key TEXT,\n                template_name TEXT NOT NULL,\n                template_type TEXT,\n                original_file_path TEXT,\n                analyzed_data TEXT,\n                editable_config TEXT,\n                zone_config TEXT,\n                merged_cells_config TEXT,\n                style_config TEXT,\n                business_rules TEXT,\n                is_active INTEGER DEFAULT 1,\n                tenant_id INTEGER,\n                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n            )\n            ')
        cur.execute('\n            CREATE TABLE IF NOT EXISTS template_usage_log (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                template_id INTEGER NOT NULL,\n                action TEXT NOT NULL,\n                result TEXT,\n                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n            )\n            ')
        cur.execute('\n            CREATE INDEX IF NOT EXISTS idx_templates_type_active\n            ON templates (template_type, is_active)\n            ')
        cur.execute('\n            CREATE INDEX IF NOT EXISTS idx_template_usage_log_template_id\n            ON template_usage_log (template_id)\n            ')
        cur.execute('PRAGMA table_info(templates)')
        templates_columns = {str(row[1]).strip() for row in cur.fetchall() or []}
        required_templates_columns = {'template_key': 'ALTER TABLE templates ADD COLUMN template_key TEXT', 'template_name': 'ALTER TABLE templates ADD COLUMN template_name TEXT', 'template_type': 'ALTER TABLE templates ADD COLUMN template_type TEXT', 'original_file_path': 'ALTER TABLE templates ADD COLUMN original_file_path TEXT', 'analyzed_data': 'ALTER TABLE templates ADD COLUMN analyzed_data TEXT', 'editable_config': 'ALTER TABLE templates ADD COLUMN editable_config TEXT', 'zone_config': 'ALTER TABLE templates ADD COLUMN zone_config TEXT', 'merged_cells_config': 'ALTER TABLE templates ADD COLUMN merged_cells_config TEXT', 'style_config': 'ALTER TABLE templates ADD COLUMN style_config TEXT', 'business_rules': 'ALTER TABLE templates ADD COLUMN business_rules TEXT', 'is_active': 'ALTER TABLE templates ADD COLUMN is_active INTEGER DEFAULT 1', 'created_at': 'ALTER TABLE templates ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP', 'updated_at': 'ALTER TABLE templates ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP', 'tenant_id': 'ALTER TABLE templates ADD COLUMN tenant_id INTEGER'}
        for (column_name, sql) in required_templates_columns.items():
            if column_name not in templates_columns:
                cur.execute(sql)
        cur.execute('PRAGMA table_info(template_usage_log)')
        usage_columns = {str(row[1]).strip() for row in cur.fetchall() or []}
        required_usage_columns = {'template_id': 'ALTER TABLE template_usage_log ADD COLUMN template_id INTEGER', 'action': 'ALTER TABLE template_usage_log ADD COLUMN action TEXT', 'result': 'ALTER TABLE template_usage_log ADD COLUMN result TEXT', 'created_at': 'ALTER TABLE template_usage_log ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP'}
        for (column_name, sql) in required_usage_columns.items():
            if column_name not in usage_columns:
                cur.execute(sql)
        conn.commit()

def init_template_tables_for_engine(engine: Engine) -> None:
    """
    在主库（PostgreSQL）上创建 templates / template_usage_log。
    与 Alembic f0c2a8e1_templates 对齐；启动时幂等补齐，便于未跑迁移的环境。
    """
    from sqlalchemy import inspect, text
    if engine.dialect.name != 'postgresql':
        return
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    with engine.begin() as conn:
        if 'templates' not in existing:
            conn.execute(text('\n                    CREATE TABLE templates (\n                        id BIGSERIAL PRIMARY KEY,\n                        template_key TEXT,\n                        template_name TEXT NOT NULL,\n                        template_type TEXT,\n                        original_file_path TEXT,\n                        analyzed_data TEXT,\n                        editable_config TEXT,\n                        zone_config TEXT,\n                        merged_cells_config TEXT,\n                        style_config TEXT,\n                        business_rules TEXT,\n                        is_active INTEGER DEFAULT 1,\n                        tenant_id INTEGER,\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    '))
        if 'template_usage_log' not in existing:
            conn.execute(text('\n                    CREATE TABLE template_usage_log (\n                        id BIGSERIAL PRIMARY KEY,\n                        template_id BIGINT NOT NULL REFERENCES templates(id) ON DELETE CASCADE,\n                        action TEXT NOT NULL,\n                        result TEXT,\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    '))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_templates_type_active ON templates (template_type, is_active)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_template_usage_log_template_id ON template_usage_log (template_id)'))

def _resolve_auth_bootstrap_engine(engine: Engine | None=None, *, database_url: str | None=None) -> Engine | None:
    from sqlalchemy.engine import Engine as _Engine
    real_engine: _Engine | None = None
    url = (database_url or '').strip()
    if url:
        try:
            from app.db import _create_engine_for_url
            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning('auth bootstrap: 无法按 DATABASE_URL 创建引擎: %s', exc)
    if real_engine is None and engine is not None:
        if isinstance(engine, _Engine):
            real_engine = engine
        else:
            try:
                from app.db import _get_engine as _get_real_engine
                real_engine = _get_real_engine()
            except _facade().RECOVERABLE_ERRORS:
                real_engine = None
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine
            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
            return None
    return real_engine

def _seed_default_admin_user(real_engine: Engine) -> None:
    from sqlalchemy import text
    from app.utils.security.password_hash import generate_password_hash
    from app.utils.time import utc_now_naive
    with real_engine.connect() as conn:
        n = conn.execute(text('SELECT COUNT(*) FROM users')).scalar()
    if int(n or 0) != 0:
        return
    username = (_facade().os.environ.get('ADMIN_USERNAME') or 'admin').strip()
    password = (_facade().os.environ.get('ADMIN_PASSWORD') or 'admin123').strip()
    display_name = (_facade().os.environ.get('ADMIN_DISPLAY_NAME') or '管理员').strip() or '管理员'
    if not username or not password:
        _facade().logger.warning('auth bootstrap: users 为空但未配置 ADMIN_USERNAME/ADMIN_PASSWORD，跳过种子')
        return
    hp = generate_password_hash(password)
    with real_engine.begin() as conn:
        conn.execute(text("\n                INSERT INTO users (\n                    username, password, display_name, email, role,\n                    is_active, mfa_enabled, tier, industry_id, created_at,\n                    failed_login_attempts, email_verified\n                )\n                VALUES (\n                    :username, :password, :display_name, :email, 'admin',\n                    TRUE, FALSE, 'admin', :industry_id, :now,\n                    0, FALSE\n                )\n                "), {'username': username, 'password': hp, 'display_name': display_name, 'email': f'{username}@local', 'industry_id': '通用', 'now': utc_now_naive()})
    _facade().logger.info('已写入初始管理员账户（username=%s）', username)

def ensure_sqlite_auth_bootstrap(engine: Engine | None=None, *, database_url: str | None=None, swallow_errors: bool=True) -> None:
    """桌面 SQLite 首启：创建 users/sessions 并写入默认管理员，避免 /api/auth/login 500。"""
    from sqlalchemy import inspect
    from app.db.base import Base
    from app.db.models.user import Session, User
    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != 'sqlite':
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if 'users' not in tables or 'sessions' not in tables:
            _facade().logger.info('SQLite 缺少 users/sessions，正在通过 ORM 创建 …')
            Base.metadata.create_all(real_engine, tables=[_facade()._orm_table(User), _facade()._orm_table(Session)], checkfirst=True)
        _facade()._seed_default_admin_user(real_engine)
    except _facade().RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            _facade().logger.warning('ensure_sqlite_auth_bootstrap 失败: %s', exc, exc_info=True)
            return
        raise

def _seed_sqlite_rbac_defaults(real_engine: Engine) -> None:
    from sqlalchemy import inspect
    from sqlalchemy.orm import sessionmaker
    from app.db.models.permission import DEFAULT_PERMISSIONS, DEFAULT_ROLES, Permission, Role
    if not {'permissions', 'roles', 'role_permissions'}.issubset(set(inspect(real_engine).get_table_names() or [])):
        return
    SessionLocal = sessionmaker(bind=real_engine)
    with SessionLocal() as session:
        perm_by_code = {perm.code: perm for perm in session.query(Permission).all()}
        for row in DEFAULT_PERMISSIONS:
            perm = perm_by_code.get(row['code'])
            if perm is None:
                perm = Permission(name=row['name'], code=row['code'], description=row.get('description', ''), module=row.get('module', ''))
                session.add(perm)
                perm_by_code[row['code']] = perm
        session.flush()
        role_by_name = {role.name: role for role in session.query(Role).all()}
        for role_row in DEFAULT_ROLES:
            role = role_by_name.get(role_row['name'])
            if role is None:
                role = Role(name=role_row['name'], description=role_row.get('description', ''), is_system=True)
                session.add(role)
                role_by_name[role.name] = role
            assigned = {permission.code for permission in role.permissions}
            for code in role_row.get('permissions', []):
                perm = perm_by_code.get(code)
                if perm is not None and code not in assigned:
                    role.permissions.append(perm)
                    assigned.add(code)
        session.commit()
    _facade().logger.info('SQLite RBAC 默认权限/角色已增量同步')
