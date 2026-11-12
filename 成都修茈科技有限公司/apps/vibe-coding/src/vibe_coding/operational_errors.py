"""Auditable exception policies for integration and lifecycle boundaries.

The workflow engine intentionally isolates failures raised by user-provided
tools, optional providers, parsers, and sandbox adapters.  Keeping those
catch-all boundaries behind named policies makes them distinguishable from
accidental broad exception handling.
"""

BOUNDARY_ERRORS = (Exception,)
TERMINATION_ERRORS = (BaseException,)

__all__ = ("BOUNDARY_ERRORS", "TERMINATION_ERRORS")
