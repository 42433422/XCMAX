"""Application-layer decorators for transaction boundaries."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from app.errors import AppError, ErrorCode
from app.infrastructure.persistence.sqlalchemy_uow import SqlAlchemyUnitOfWork

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def transactional(method: F) -> F:
    """
    Wrap a service method that accepts ``db`` as its first argument after ``self``.

    The wrapped method runs inside ``SqlAlchemyUnitOfWork``; unexpected exceptions
    become ``AppError(INTERNAL_ERROR)`` instead of ad-hoc error_id dicts.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with SqlAlchemyUnitOfWork() as db:
            try:
                return method(self, db, *args, **kwargs)
            except AppError:
                raise
            except Exception as exc:
                logger.exception("%s failed", method.__name__)
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    "操作失败，请稍后重试",
                    status_code=500,
                    detail={"cause": str(exc)},
                ) from exc

    return wrapper  # type: ignore[return-value]
