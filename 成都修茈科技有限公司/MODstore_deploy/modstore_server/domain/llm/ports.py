"""LLM domain ports."""

from __future__ import annotations

from typing import Any, Protocol

from modstore_server.domain.llm.types import LlmCredential


class LlmCredentialRepository(Protocol):
    def get_for_user(self, user_id: int, provider: str) -> LlmCredential | None: ...

    def save_encrypted_blob(self, user_id: int, provider: str, blob: bytes) -> None: ...


class LlmKeyResolverPort(Protocol):
    """Resolve effective API key / base URL for outbound provider calls."""

    def resolve(self, *, user_id: int, provider: str, model: str) -> dict[str, Any]: ...


__all__ = ["LlmCredentialRepository", "LlmKeyResolverPort"]
