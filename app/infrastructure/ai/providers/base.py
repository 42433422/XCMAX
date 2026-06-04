"""AI Provider 抽象基类与公共数据结构（阶段 8）。

统一三类能力：
- ``CHAT``   对话补全
- ``INTENT`` 意图识别
- ``TTS``    文本转语音

每个 Provider 声明：
- ``name``           唯一标识（如 "deepseek"）
- ``tier``           部署档位（local / edge / cloud）
- ``capabilities``   支持的能力集合
- ``is_available()`` 依赖/密钥就绪检测（用于优雅降级与路由）

Provider 永远不应在 import 期硬失败（缺依赖时 ``is_available()`` 返回 False）。
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from typing import Any


class Capability(str, enum.Enum):
    CHAT = "chat"
    INTENT = "intent"
    TTS = "tts"


class Tier(str, enum.Enum):
    """部署档位，用于三档路由。"""

    LOCAL = "local"   # 进程内 / 本机（Ollama、嵌入式 BERT/RASA）
    EDGE = "edge"     # 同机房 / 局域网自托管推理服务
    CLOUD = "cloud"   # 公有云 API（DeepSeek / OpenAI 等）


@dataclass
class ProviderResult:
    """Provider 调用的统一返回。"""

    success: bool
    capability: Capability
    provider: str
    data: Any = None
    error: str | None = None
    latency_ms: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class BaseProvider(abc.ABC):
    """所有 AI Provider 的抽象基类。"""

    name: str = "base"
    tier: Tier = Tier.CLOUD
    capabilities: frozenset[Capability] = frozenset()

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    @abc.abstractmethod
    def is_available(self) -> bool:
        """依赖与配置是否就绪（密钥、模型文件、远端可达等）。"""
        raise NotImplementedError

    # 以下能力方法默认抛 NotImplementedError；Provider 仅实现其声明的能力。
    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ProviderResult:
        raise NotImplementedError(f"{self.name} 不支持 chat")

    async def recognize_intent(
        self, message: str, context: list[dict[str, str]] | None = None, **kwargs: Any
    ) -> ProviderResult:
        raise NotImplementedError(f"{self.name} 不支持 intent")

    async def synthesize(self, text: str, voice: str | None = None, **kwargs: Any) -> ProviderResult:
        raise NotImplementedError(f"{self.name} 不支持 tts")

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tier": self.tier.value,
            "capabilities": sorted(c.value for c in self.capabilities),
            "available": self.is_available(),
        }
