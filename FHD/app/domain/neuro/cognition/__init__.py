"""认知层（Cognition Layer）—— Conscious 处理器的 LLM 能力升级。

Phase 2 组件：
- ``LLMPort``：LLM 端口适配器，封装现有 ``LLMProviderRegistry``，不锁定到任何 LLM 提供方。
- ``WorkingMemory``：工作记忆，会话级短期记忆 + 可选长期向量召回。
- ``AttentionSelector``：注意力选择器，从工作记忆中选取与当前查询最相关的上下文。
- ``ConsciousLLMHandler``：Conscious 处理器的默认 LLM 处理器，整合上述三者。

设计原则：
1. 不重新发明 LLM 抽象——复用 ``app/infrastructure/llm/providers/`` 已有的 Protocol + Registry。
2. 不锁定 LLM 提供方——Registry 已支持 20+ provider（DeepSeek/OpenAI/Xiaomi/SiliconFlow…）。
3. best-effort——任何后端不可用都降级为空，不阻断 Conscious 处理（与 EmployeeMemoryManager 一致）。
4. SLA 感知——Conscious 目标 <200ms，但 LLM 调用可能超时；SLA 控制器记录违规但不杀请求。
"""

from app.domain.neuro.cognition.attention_selector import AttentionResult, AttentionSelector
from app.domain.neuro.cognition.conscious_llm_handler import ConsciousLLMHandler
from app.domain.neuro.cognition.llm_port import LLMPort, get_llm_port, reset_llm_port
from app.domain.neuro.cognition.working_memory import (
    WorkingMemory,
    get_working_memory,
    reset_working_memory,
)

__all__ = [
    "LLMPort",
    "get_llm_port",
    "reset_llm_port",
    "WorkingMemory",
    "get_working_memory",
    "reset_working_memory",
    "AttentionSelector",
    "AttentionResult",
    "ConsciousLLMHandler",
]
