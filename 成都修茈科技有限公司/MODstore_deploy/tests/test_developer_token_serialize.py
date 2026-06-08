"""PAT 序列化依赖的 UTC 时间比较（naive DB 时间）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from modstore_server.datetime_utils import as_utc_aware


def test_naive_expires_at_compares_with_utc_now():
    now = datetime.now(timezone.utc)
    naive_future = (now + timedelta(days=30)).replace(tzinfo=None)
    exp = as_utc_aware(naive_future)
    assert exp is not None
    assert exp > now
