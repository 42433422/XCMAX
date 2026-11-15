"""Account kind values shared by domain ports and application services."""

from __future__ import annotations

from typing import Literal

AccountKind = Literal["personal", "enterprise", "admin"]
VALID_ACCOUNT_KINDS: frozenset[str] = frozenset({"personal", "enterprise", "admin"})
