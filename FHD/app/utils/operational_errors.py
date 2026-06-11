"""Narrow exception tuples for non-boundary catch sites.

Route-level catch-all lives in ``app.middleware.error_handler``; inner code should
only handle operational failures and let unexpected errors propagate.
"""

from __future__ import annotations

import json

_operational_extra: tuple[type[BaseException], ...] = ()
try:
    from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

    _operational_extra = (SQLAlchemyOperationalError,)
except ImportError:
    pass

OPERATIONAL_ERRORS: tuple[type[BaseException], ...] = (
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
    *_operational_extra,
)
