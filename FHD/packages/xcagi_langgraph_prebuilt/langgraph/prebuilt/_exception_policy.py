"""Auditable exception families used by prebuilt tool boundaries."""

BOUNDARY_ERRORS: tuple[type[Exception], ...] = (Exception,)
TERMINATION_ERRORS: tuple[type[BaseException], ...] = (BaseException,)
