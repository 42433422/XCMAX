"""Excel/extract/vector ports (canonical)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ExtractLogStorePort(ABC):
    """提取日志仓储端口"""

    @abstractmethod
    def find_all(
        self, page: int = 1, per_page: int = 20, unit_name: str | None = None
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def find_by_id(self, log_id: int) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def create(self, log_data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, log_id: int) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def clear_old(self, days: int = 30) -> dict[str, Any]:
        raise NotImplementedError


class FileAnalysisPort(ABC):
    """文件分析端口"""

    @abstractmethod
    def analyze_file(self, upload_file, purpose: str = "general") -> dict[str, Any]:
        raise NotImplementedError


class VectorStorePort(ABC):
    """向量存储端口。"""

    @abstractmethod
    def upsert_chunks(
        self,
        index_id: str,
        chunks: list[dict[str, Any]],
    ) -> int:
        """写入分块向量数据并返回写入数量。"""
        raise NotImplementedError

    @abstractmethod
    def query(
        self,
        index_id: str,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """检索相似分块。"""
        raise NotImplementedError

    @abstractmethod
    def list_indexes(self) -> list[dict[str, Any]]:
        """返回索引列表与状态。"""
        raise NotImplementedError

    @abstractmethod
    def delete_index(self, index_id: str) -> bool:
        """删除索引。"""
        raise NotImplementedError
