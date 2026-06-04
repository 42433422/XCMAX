"""AI 基础设施层（阶段 8）。

统一的 AI Provider 抽象、注册表与三档（本地/边缘/云端）模型路由。
对外暴露稳定的 ``providers`` 与 ``router`` 接口，业务层不再直接依赖
``ai_engines`` / ``services`` 中分散的具体实现。
"""

from __future__ import annotations

__all__ = ["providers", "router"]
