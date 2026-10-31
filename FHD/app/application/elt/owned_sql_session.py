"""One pinned physical SQLite connection implementation for owned/ETL consumers.

No creation, retry, adoption or independent variant of the connection guard.
"""

import os
from contextlib import contextmanager
from inspect import getclosurevars
from pathlib import Path

from sqlalchemy import URL
from sqlalchemy import __version__ as sqlalchemy_version
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.application.elt.errors import EltError
from app.desktop_runtime.database_generation_registry import GenerationObservationError


def _read_only_url(target):
    return URL.create(
        "sqlite+pysqlite", database=target.resolve().as_uri(), query={"mode": "ro", "uri": "true"}
    )


def _readback_url(bind):
    engine = getattr(bind, "engine", bind)
    database = engine.url.database
    if (
        engine.dialect.name != "sqlite"
        or engine.url.drivername not in {"sqlite", "sqlite+pysqlite"}
        or not database
        or database == ":memory:"
        or database.startswith("file:")
    ):
        raise EltError("ELT_BATCH_READBACK_UNSUPPORTED", "独立读回目前要求普通文件型 SQLite")
    return _read_only_url(Path(database))


def _target_database(bind):
    # Validate without opening a connection. Ordinary DBAPI tuning is compatible;
    # URI and unknown query options cannot select an alternative target.
    _readback_url(bind)
    engine = getattr(bind, "engine", bind)
    allowed = {
        "timeout",
        "isolation_level",
        "detect_types",
        "check_same_thread",
        "cached_statements",
    }
    if set(engine.url.query) - allowed:
        raise GenerationObservationError("ordinary SQLite target required")
    return Path(engine.url.database).absolute()


def _assert_target_connection(connection, target):
    # URL metadata alone is insufficient: custom creators and dynamic session
    # factories can point elsewhere. Inspect the actual connection before DML.
    rows = connection.exec_driver_sql("PRAGMA database_list").fetchall()
    main = [row[2] for row in rows if row[1] == "main"]
    if (
        len(main) != 1
        or not main[0]
        or any(row[1] not in {"main", "temp"} for row in rows)
        or os.path.normcase(str(Path(main[0]).resolve())) != os.path.normcase(str(target.resolve()))
    ):
        raise GenerationObservationError("actual database differs from locked target")


@contextmanager
def _fresh_target_session(factory, target, *, read_only=False):
    """Use one fresh physical connection, preserving host pool/engine hooks.

    This compatibility boundary supports standard pysqlite creators and idle,
    non-routing Sessions only, with no do_connect replacement hooks.
    Recreating the pool avoids checkout of an old
    inode after restore; reconnect is disabled for the pinned Connection.
    """
    from app.application.elt.batch_owned_source import OwnedSqlSessions
    from app.mod_sdk.owned_price_catalog import CatalogPurpose

    if isinstance(factory, OwnedSqlSessions):
        if factory.target != target or (read_only and factory.purpose is not CatalogPurpose.READ):
            raise GenerationObservationError("owned catalog target changed")
        with factory() as db:
            yield db
        return
    with factory() as db:
        bind = db.get_bind()
        if (
            not isinstance(bind, Engine)
            or bind.dialect.name != "sqlite"
            or type(db).get_bind is not Session.get_bind
            or db.in_transaction()
            or db.new
            or db.dirty
            or db.deleted
            or getattr(db, "binds", None)
            or getattr(db, "_Session__binds", None)
            or (
                bind.url != _read_only_url(target)
                if read_only
                else _target_database(bind).resolve() != target.resolve()
            )
        ):
            raise GenerationObservationError("unsupported target session")
        # The private creator shape is deliberately bounded and checked, not
        # assumed stable across SQLAlchemy releases. Production supports 2.0/2.1.
        if (
            tuple(sqlalchemy_version.split(".")[:2]) not in {("2", "0"), ("2", "1")}
            or type(bind.pool).__module__ != "sqlalchemy.pool.impl"
            or bind.dialect.dispatch.do_connect
        ):
            raise GenerationObservationError("unsupported SQLAlchemy connection implementation")
        creator = bind.pool._creator
        if (
            getattr(creator, "__module__", None) != "sqlalchemy.engine.create"
            or getattr(creator, "__qualname__", None) != "create_engine.<locals>.connect"
        ):
            raise GenerationObservationError("custom SQLite creator is unsupported")
        settings = getclosurevars(creator).nonlocals
        args = settings.get("cargs_tup", settings.get("cargs"))
        options = settings.get("cparams", {})
        if (
            not isinstance(args, (tuple, list))
            or len(args) != 1
            or not isinstance(args[0], str)
            or (
                args[0] != target.resolve().as_uri() + "?mode=ro"
                if read_only
                else args[0].startswith("file:") or Path(args[0]).resolve() != target.resolve()
            )
            or set(options)
            - {
                "timeout",
                "isolation_level",
                "detect_types",
                "check_same_thread",
                "cached_statements",
                "uri",
            }
            or options.get("uri", False) is not read_only
        ):
            raise GenerationObservationError("unsupported SQLite connection arguments")
        pool = bind.pool.recreate()
        try:
            with Connection(bind, connection=pool.connect(), _allow_revalidate=False) as connection:
                _assert_target_connection(connection, target)
                connection.rollback()  # End diagnostic autobegin before Session owns the transaction.
                db.bind = connection
                try:
                    yield db
                finally:
                    db.close()  # rollback must finish while the target lock is still held
        finally:
            pool.dispose()
