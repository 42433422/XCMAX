"""
NeuroBus 纯异步命令入口（fire-and-forget publish）。

HTTP 同步 mutation 请使用 ``app.application.facades.*_event_primary`` +
``app.bootstrap.get_*_app_service()``（CommandGateway request-reply），
勿在路由中直接调用 ``get_neuro_command_service``。
"""

from app.application.neuro_commands.registry import (
    NEURO_COMMAND_DOMAINS,
    get_neuro_command_service,
    reset_neuro_command_services,
)

__all__ = [
    "NEURO_COMMAND_DOMAINS",
    "get_neuro_command_service",
    "reset_neuro_command_services",
]
