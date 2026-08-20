"""Auditable exception families used by SDK transport boundaries."""

BOUNDARY_ERRORS: tuple[type[Exception], ...] = (Exception,)
TERMINATION_ERRORS: tuple[type[BaseException], ...] = (BaseException,)
