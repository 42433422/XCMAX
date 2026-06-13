"""Narrow exception tuples for non-boundary catch sites.

Route-level catch-all lives in ``app.middleware.error_handler``; inner code should
only handle operational failures and let unexpected errors propagate.

Programming bugs (``TypeError``, ``KeyError``, ``AttributeError``) are intentionally
excluded — they should bubble to the HTTP boundary as 500s.
"""

from __future__ import annotations

import json

_operational_extra: tuple[type[BaseException], ...] = ()
try:
    from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

    _operational_extra = (SQLAlchemyOperationalError,)
except ImportError:
    pass

_httpx_extra: tuple[type[BaseException], ...] = ()
try:
    import httpx

    _httpx_extra = (httpx.HTTPError, httpx.TransportError)
except ImportError:
    pass

# L2: infrastructure transient failures (IO, network, external deps)
INFRA_TRANSIENT: tuple[type[BaseException], ...] = (
    OSError,
    ConnectionError,
    TimeoutError,
    RuntimeError,
    ImportError,
    ArithmeticError,
    *_operational_extra,
    *_httpx_extra,
)

# L2: data shape / parsing failures (often map to 400/422)
DATA_SHAPE: tuple[type[BaseException], ...] = (
    ValueError,
    json.JSONDecodeError,
    UnicodeError,
    LookupError,
)

# Union of recoverable operational failures (default inner catch tuple)
RECOVERABLE_ERRORS: tuple[type[BaseException], ...] = INFRA_TRANSIENT + DATA_SHAPE
