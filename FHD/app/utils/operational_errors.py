"""Narrow exception tuples for non-boundary catch sites.

Route-level catch-all lives in ``app.middleware.error_handler``; inner code should
only handle operational failures and let unexpected errors propagate.

Programming bugs (``TypeError``, ``KeyError``, ``AttributeError``) are intentionally
excluded — they should bubble to the HTTP boundary as 500s.
"""

from __future__ import annotations

import json
import sqlite3

# Legacy alias for im-sync-backend compatibility
OPERATIONAL_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    RuntimeError,
    ImportError,
    LookupError,
    ConnectionError,
    TimeoutError,
    json.JSONDecodeError,
    ArithmeticError,
    UnicodeError,
)

_operational_extra: tuple[type[Exception], ...] = ()
try:
    from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

    _operational_extra = (SQLAlchemyOperationalError,)
except ImportError:
    pass

_httpx_extra: tuple[type[Exception], ...] = ()
try:
    import httpx

    _httpx_extra = (httpx.HTTPError, httpx.TransportError)
except ImportError:
    pass

# aiohttp（edge-tts / 语音上游 WebSocket）的异常不继承内建 OSError/ConnectionError，
# 也不在 httpx 族里；不显式纳入时，握手 403 或超时会穿透到 HTTP 边界变成 500。
_aiohttp_extra: tuple[type[Exception], ...] = ()
try:
    import aiohttp

    _aiohttp_extra = (aiohttp.ClientError, aiohttp.ClientConnectionError)
except ImportError:
    pass

# redis-py 的连接/超时错误继承自 ``redis.exceptions.RedisError(Exception)``，
# 而非内建 ``ConnectionError``/``TimeoutError``（OSError 族），因此必须显式纳入，
# 否则 redis 宕机时所有 ``except RECOVERABLE_ERRORS`` 探针都会 500。
_redis_extra: tuple[type[Exception], ...] = ()
try:
    from redis.exceptions import ConnectionError as _RedisConnectionError
    from redis.exceptions import TimeoutError as _RedisTimeoutError

    _redis_extra = (_RedisConnectionError, _RedisTimeoutError)
except ImportError:
    pass

# L2: infrastructure transient failures (IO, network, external deps)
INFRA_TRANSIENT: tuple[type[Exception], ...] = (
    OSError,
    sqlite3.DatabaseError,
    ConnectionError,
    TimeoutError,
    RuntimeError,
    ImportError,
    ArithmeticError,
    *_operational_extra,
    *_httpx_extra,
    *_aiohttp_extra,
    *_redis_extra,
)

# L2: data shape / parsing failures (often map to 400/422)
DATA_SHAPE: tuple[type[Exception], ...] = (
    ValueError,
    json.JSONDecodeError,
    UnicodeError,
    LookupError,
)

# Union of recoverable operational failures (default inner catch tuple)
RECOVERABLE_ERRORS: tuple[type[Exception], ...] = INFRA_TRANSIENT + DATA_SHAPE

# Only process, request, task, adapter, and plugin-isolation boundaries may
# translate an otherwise unexpected application exception. Keeping this
# separate from RECOVERABLE_ERRORS makes every deliberate catch-all auditable.
BOUNDARY_ERRORS: tuple[type[Exception], ...] = (Exception,)
