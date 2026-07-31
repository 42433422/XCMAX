"""微信消息发送服务（兼容入口）。

历史测试通过 ``app.services.wechat_sender.send_wechat_message`` 进行 mock，
实际实现已迁移至 :mod:`app.application.wechat_sender_app_service`。
本模块保留转发以避免破坏既有测试与调用方。
"""

from __future__ import annotations

from app.application.wechat_sender_app_service import send_wechat_message

__all__ = ["send_wechat_message"]
