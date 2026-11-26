"""SQLAlchemy declarative base."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql.functions import FunctionElement


class Base(DeclarativeBase):
    pass


class TrimIndexValue(FunctionElement[str]):
    """Render space trimming in the form reflected by each database."""

    type = String()
    inherit_cache = True


@compiles(TrimIndexValue)
def _trim_index_value(element, compiler, **kwargs):
    return f"trim({compiler.process(element.clauses, **kwargs)})"


@compiles(TrimIndexValue, "postgresql")
def _pg_trim_index_value(element, compiler, **kwargs):
    return f"trim(BOTH FROM {compiler.process(element.clauses, **kwargs)})"
