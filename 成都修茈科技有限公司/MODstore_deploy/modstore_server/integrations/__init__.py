"""第三方/同仓库子项目的本进程集成层。

目前只承载 vibe-coding 的接入(:mod:`.vibe_adapter`)。子模块全部做了 lazy import
+ 缺失依赖时友好降级,允许 MODstore 在 vibe-coding 未安装的情况下继续启动。
"""

from __future__ import annotations

__all__ = ["vibe_adapter", "vibe_eskill_adapter", "vibe_action_handlers"]
