"""Domain entities and invariants."""

from modstore_server.models import Base, User  # noqa: F401 — phase-1 re-export

__all__ = ["Base", "User"]
