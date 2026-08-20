"""Auditable exception families used by SQLite checkpoint boundaries."""

BOUNDARY_ERRORS: tuple[type[Exception], ...] = (Exception,)
TERMINATION_ERRORS: tuple[type[BaseException], ...] = (BaseException,)
