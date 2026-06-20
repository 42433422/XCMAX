"""Persona 画像仓储接口 (Port)。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.persona.entities import PersonaProfile


class PersonaProfileRepository(ABC):
    """Persona 画像仓储接口。"""

    @abstractmethod
    async def find_by_user_id(self, user_id: str) -> PersonaProfile | None:
        """根据用户 ID 查找画像。"""
        raise NotImplementedError

    @abstractmethod
    async def save(self, profile: PersonaProfile) -> PersonaProfile:
        """保存画像（新增或更新）。"""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, user_id: str) -> bool:
        """删除画像。"""
        raise NotImplementedError

    @abstractmethod
    async def append_event(self, user_id: str, event_type: str, event_data: dict) -> None:
        """追加事件日志（用于审计和 L3 复盘）。"""
        raise NotImplementedError

    @abstractmethod
    async def list_recent_events(self, user_id: str, limit: int = 20) -> list[dict]:
        """列出最近的事件日志。"""
        raise NotImplementedError
