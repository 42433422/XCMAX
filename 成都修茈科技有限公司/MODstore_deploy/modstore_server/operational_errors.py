"""Explicit exception families that inner recovery paths may handle.

Boundary middleware may still translate an unexpected exception to a 500 response,
but background jobs, adapters, and maintenance scripts should only absorb failures
that can reasonably come from data, I/O, dependencies, or optional integrations.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import zipfile

_optional_errors: tuple[type[Exception], ...] = ()

try:
    from sqlalchemy.exc import SQLAlchemyError

    _optional_errors += (SQLAlchemyError,)
except ImportError:  # pragma: no cover - minimal script environments
    pass

try:
    import httpx

    _optional_errors += (httpx.HTTPError,)
except ImportError:  # pragma: no cover - optional HTTP client
    pass

try:
    import requests

    _optional_errors += (requests.RequestException,)
except ImportError:  # pragma: no cover - optional HTTP client
    pass

try:
    from websockets.exceptions import WebSocketException

    _optional_errors += (WebSocketException,)
except ImportError:  # pragma: no cover - optional WebSocket client
    pass

try:
    import jwt

    _optional_errors += (jwt.PyJWTError,)
except (AttributeError, ImportError):  # pragma: no cover - optional JWT client
    pass

try:
    from cryptography.fernet import InvalidToken

    _optional_errors += (InvalidToken,)
except ImportError:  # pragma: no cover - optional crypto provider
    pass

try:
    from paramiko import SSHException

    _optional_errors += (SSHException,)
except ImportError:  # pragma: no cover - optional SSH client
    pass

try:
    from pydantic import ValidationError

    _optional_errors += (ValidationError,)
except ImportError:  # pragma: no cover - optional validation runtime
    pass

try:
    from redis.exceptions import RedisError

    _optional_errors += (RedisError,)
except ImportError:  # pragma: no cover - optional Redis client
    pass

try:
    from yaml import YAMLError

    _optional_errors += (YAMLError,)
except ImportError:  # pragma: no cover - optional YAML parser
    pass


RECOVERABLE_ERRORS: tuple[type[Exception], ...] = (
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
    sqlite3.DatabaseError,
    subprocess.SubprocessError,
    zipfile.BadZipFile,
    ArithmeticError,
    UnicodeError,
    *_optional_errors,
)

# Only top-level process, request, task, and plugin-isolation boundaries may use
# this alias.  Naming it separately makes those deliberate catch-all contracts
# auditable without hiding broad catches among ordinary recovery paths.
BOUNDARY_ERRORS: tuple[type[Exception], ...] = (Exception,)
