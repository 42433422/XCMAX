"""Auditable exception families used by LangGraph runtime boundaries."""

BOUNDARY_ERRORS: tuple[type[Exception], ...] = (Exception,)
TERMINATION_ERRORS: tuple[type[BaseException], ...] = (BaseException,)
