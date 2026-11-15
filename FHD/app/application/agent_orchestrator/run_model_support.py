"""Primitive value helpers shared by persisted agent-run models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.utils.scalars import coerce_float as coerce_float
from app.utils.scalars import coerce_int as coerce_int


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
