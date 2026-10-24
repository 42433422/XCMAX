"""Desktop database locations and isolated, non-overwriting SQLite seed copies."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Any

from app.db.bootstrap.contracts import SqliteConnection
from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix
from app.utils.operational_errors import RECOVERABLE_ERRORS


def desktop_data_root(
    data_dir: str | None, environment: Mapping[str, str], app_data_dir: Callable[[], str]
) -> Path:
    return Path(data_dir or environment.get("XCAGI_DATA_DIR") or app_data_dir()).expanduser()


def create_desktop_business_tables(
    db_path: Path, connect: Callable[[Path], sqlite3.Connection]
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS purchase_units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unit_name TEXT NOT NULL DEFAULT '', contact_person TEXT,
                contact_phone TEXT, address TEXT, is_active BOOLEAN DEFAULT 1,
                tenant_id INTEGER, unit_code TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT '', model_number TEXT NOT NULL DEFAULT '',
                unit TEXT NOT NULL DEFAULT '', purchase_unit_id INTEGER, tenant_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.commit()


def ensure_desktop_files(root: Path, ensure_tables: Callable[[Path], None]) -> None:
    data_root = root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    candidates = {
        path for directory in (data_root, root) for path in directory.glob("*.db") if path.is_file()
    }
    for path in sorted(candidates or {data_root / "xcagi.db"}):
        ensure_tables(path)


def select_environment(
    *,
    desktop: bool,
    environment: MutableMapping[str, str],
    root: Callable[[], Path],
    ensure_tables: Callable[[str], None],
    refresh_config: Callable[[], None],
) -> str:
    if not desktop:
        return environment.get("DATABASE_URL", "")
    data_root = root() / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{data_root / 'xcagi.db'}"
    environment["DATABASE_URL"] = url
    environment["DATABASE_PATH"] = str(data_root)
    ensure_tables(str(data_root.parent))
    try:
        refresh_config()
    except RECOVERABLE_ERRORS:
        pass
    return url


@dataclass(frozen=True)
class DatabaseFiles:
    app_data_dir: Callable[[], str]
    seed_dirs: Callable[[], Iterable[str]]
    sqlite_connect: SqliteConnection
    copy_file: Callable[[str, str], str]
    logger: Logger

    def initialize(self, db_files: Iterable[str]) -> None:
        work_dir = self.app_data_dir()
        os.makedirs(work_dir, exist_ok=True)
        for db_file in db_files:
            target = os.path.join(work_dir, db_file)
            if os.path.exists(target):
                continue
            source = next(
                (
                    candidate
                    for directory in self.seed_dirs()
                    if os.path.exists(candidate := os.path.join(directory, db_file))
                ),
                None,
            )
            if source is None:
                self.logger.warning("未找到种子数据库文件：%s（将由 ORM/运行时创建）", db_file)
                continue
            try:
                self.copy_file(source, target)
                with self.sqlite_connect(target) as connection:
                    cursor = connection.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    cursor.fetchall()
            except RECOVERABLE_ERRORS as exc:
                self.logger.warning("复制数据库失败 %s -> %s: %s", source, target, exc)

    def copy_for_mods(self, mod_ids: Sequence[str], db_files: Iterable[str]) -> None:
        work_dir = self.app_data_dir()
        os.makedirs(work_dir, exist_ok=True)
        seen: set[str] = set()
        for raw_id in mod_ids:
            mod_id = str(raw_id or "").strip()
            if not mod_id or mod_id in seen:
                continue
            seen.add(mod_id)
            for db_name in db_files:
                source = os.path.join(work_dir, db_name)
                filename = sqlite_filename_with_mod_suffix(db_name, mod_id)
                destination = os.path.join(work_dir, filename)
                if filename == db_name or os.path.exists(destination):
                    continue
                if not os.path.exists(source):
                    self.logger.warning(
                        "无法为 Mod %s 准备专用库：母库不存在 %s（跳过 %s）",
                        mod_id,
                        source,
                        filename,
                    )
                    continue
                try:
                    self.copy_file(source, destination)
                    self.logger.info("已为 Mod %s 从母库复制专用 SQLite：%s", mod_id, filename)
                except RECOVERABLE_ERRORS as exc:
                    self.logger.warning(
                        "复制 Mod 专用库失败 mod=%s %s -> %s: %s", mod_id, source, destination, exc
                    )


def build_mod_seed_plan(work_dir: str, mods: Sequence[object]) -> dict[str, Any]:
    architecture_note_zh = "SQLite：先有母库（如 products.db，来自 resources/db_seed），每个扩展使用独立文件名（如 products__<mod>.db）；启动时若专用文件不存在，会从母库复制一份作为初始种子，之后各包数据互不影响。PostgreSQL 默认仍共用 DATABASE_URL 中的库；需要一包一库时请设置 XCAGI_MOD_ISOLATED_DATABASES=1 或为各包配置 XCAGI_MOD_DATABASE_URL_*。"
    result: list[dict[str, Any]] = []
    for mod in mods:
        mod_id = str(getattr(mod, "id", "") or "").strip()
        if not mod_id:
            continue
        notes = ""
        extra_seeds: list[dict[str, str]] = []
        mod_path = str(getattr(mod, "mod_path", "") or "").strip()
        manifest = os.path.join(mod_path, "manifest.json")
        if mod_path and os.path.isfile(manifest):
            try:
                with open(manifest, encoding="utf-8") as stream:
                    data = json.load(stream)
                database = data.get("database") if isinstance(data.get("database"), dict) else {}
                notes = str(database.get("notes_zh") or data.get("database_notes_zh") or "").strip()
                files = database.get("seed_files") or data.get("database_seed_files") or []
                if isinstance(files, list):
                    for relative in files:
                        relative_path = str(relative or "").strip()
                        if relative_path:
                            extra_seeds.append(
                                {"path": os.path.normpath(os.path.join(mod_path, relative_path))}
                            )
                seed_sql = database.get("seed_sql") or data.get("database_seed_sql")
                if seed_sql:
                    sql_path = os.path.normpath(os.path.join(mod_path, str(seed_sql).strip()))
                    if os.path.isfile(sql_path):
                        extra_seeds.append({"path": sql_path})
            except RECOVERABLE_ERRORS:
                pass
        seeds = [
            {"path": os.path.join(work_dir, "products.db"), "role": "sqlite_mother_products"},
            {
                "path": os.path.join(
                    work_dir, sqlite_filename_with_mod_suffix("products.db", mod_id)
                ),
                "role": "sqlite_per_mod_products",
            },
            *extra_seeds,
        ]
        result.append({"mod_id": mod_id, "database_notes": notes, "seeds": seeds})
    return {"architecture_note_zh": architecture_note_zh, "mods": result}
