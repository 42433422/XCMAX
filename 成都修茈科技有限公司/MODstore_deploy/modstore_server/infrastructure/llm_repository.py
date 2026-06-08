"""LLM credential persistence (复用 ``llm_crypto`` 加解密在调用点完成)."""

from __future__ import annotations


class InMemoryLlmCredentialRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[int, str], str] = {}

    def put_encrypted(self, user_id: int, provider: str, ciphertext: str) -> None:
        self.rows[(user_id, provider)] = ciphertext

    def get_encrypted(self, user_id: int, provider: str) -> str | None:
        return self.rows.get((user_id, provider))


__all__ = ["InMemoryLlmCredentialRepository"]
