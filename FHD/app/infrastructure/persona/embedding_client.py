"""外部 embedding API 客户端。"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """外部 embedding API 客户端（零硬件，调外部 API）。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "text-embedding-3-small",
        timeout: float = 10.0,
    ):
        self.api_key = api_key or os.getenv("XCAGI_EMBEDDING_API_KEY", "")
        self.base_url = base_url or os.getenv(
            "XCAGI_EMBEDDING_BASE_URL", "https://api.openai.com/v1"
        )
        self.model = model
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """调用 embedding API 生成向量。

        Args:
            texts: 待向量化的文本列表

        Returns:
            list[list[float]]: 向量列表

        Raises:
            Exception: API 调用失败时抛出
        """
        if not self.is_configured:
            raise RuntimeError("Embedding API key 未配置")
        if not texts:
            return []

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {"model": self.model, "input": texts}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/embeddings", headers=headers, json=payload
            )
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]
