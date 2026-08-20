"""Auditable exception families used by checkpoint serialization boundaries."""

BOUNDARY_ERRORS: tuple[type[Exception], ...] = (Exception,)
TERMINATION_ERRORS: tuple[type[BaseException], ...] = (BaseException,)
