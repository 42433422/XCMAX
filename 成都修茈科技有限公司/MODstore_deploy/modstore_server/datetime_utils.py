"""将 DB 读出的 naive datetime 规范为 UTC aware，避免与 datetime.now(timezone.utc) 比较报错。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def as_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
