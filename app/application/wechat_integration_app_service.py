"""微信集成 V1 应用服务。"""

from __future__ import annotations

from typing import Any

from app.infrastructure.gateways import cs_operations as cs

_wechat_integration_app_service: "WechatIntegrationApplicationService | None" = None


class WechatIntegrationApplicationService:
    def get_wechat_decrypt_status(self, *args: Any, **kwargs: Any) -> Any:
        return cs.get_wechat_decrypt_status(*args, **kwargs)

    def wechat_decrypt_auto_configure_response(self, *args: Any, **kwargs: Any) -> Any:
        return cs.wechat_decrypt_auto_configure_response(*args, **kwargs)

    def sync_group_messages(self, *args: Any, **kwargs: Any) -> Any:
        return cs.sync_group_messages(*args, **kwargs)

    def list_group_contacts(self, *args: Any, **kwargs: Any) -> Any:
        return cs.list_group_contacts(*args, **kwargs)

    def get_bindings_for_user(self, *args: Any, **kwargs: Any) -> Any:
        return cs.get_bindings_for_user(*args, **kwargs)

    def save_bindings_for_user(self, *args: Any, **kwargs: Any) -> Any:
        return cs.save_bindings_for_user(*args, **kwargs)

    def assert_safe_outbound_group_reply(self, *args: Any, **kwargs: Any) -> Any:
        return cs.assert_safe_outbound_group_reply(*args, **kwargs)

    def wechat_group_customer_bridge(self) -> Any:
        return cs.wechat_group_customer_bridge_module()

    def probe_passive_llm_ready(self, *args: Any, **kwargs: Any) -> Any:
        return cs.probe_passive_llm_ready(*args, **kwargs)

    def passive_poll_once(self, *args: Any, **kwargs: Any) -> Any:
        return cs.passive_poll_once(*args, **kwargs)

    def get_passive_poll_config(self, *args: Any, **kwargs: Any) -> Any:
        return cs.get_passive_poll_config(*args, **kwargs)

    def save_passive_poll_config(self, *args: Any, **kwargs: Any) -> Any:
        return cs.save_passive_poll_config(*args, **kwargs)

    def reset_passive_watch(self, *args: Any, **kwargs: Any) -> Any:
        return cs.reset_passive_watch(*args, **kwargs)

    def build_starred_group_feed(self, *args: Any, **kwargs: Any) -> Any:
        return cs.build_starred_group_feed(*args, **kwargs)

    def sync_bound_groups_from_live_wechat(self, *args: Any, **kwargs: Any) -> Any:
        return cs.sync_bound_groups_from_live_wechat(*args, **kwargs)

    def latest_context_message(self, messages: Any) -> Any:
        return cs._latest_context_message(messages)

    def prepare_wechat_message_db_for_read(self, *args: Any, **kwargs: Any) -> Any:
        return cs.prepare_wechat_message_db_for_read(*args, **kwargs)


def get_wechat_integration_app_service() -> WechatIntegrationApplicationService:
    global _wechat_integration_app_service
    if _wechat_integration_app_service is None:
        _wechat_integration_app_service = WechatIntegrationApplicationService()
    return _wechat_integration_app_service
