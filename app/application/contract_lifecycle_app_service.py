"""合同生命周期 V1 应用服务。"""

from __future__ import annotations

from typing import Any

from app.infrastructure.gateways import cs_operations as cs

_contract_lifecycle_app_service: ContractLifecycleApplicationService | None = None


class ContractLifecycleApplicationService:
    def esign_channel_status(self) -> Any:
        return cs.esign_channel_status()

    def get_contract_block(self, *args: Any, **kwargs: Any) -> Any:
        return cs.get_contract_block(*args, **kwargs)

    def load_pipeline(self, *args: Any, **kwargs: Any) -> Any:
        return cs.load_pipeline(*args, **kwargs)

    def save_pipeline(self, *args: Any, **kwargs: Any) -> Any:
        return cs.save_pipeline(*args, **kwargs)

    def apply_contract_to_crm_meta(self, *args: Any, **kwargs: Any) -> Any:
        return cs.apply_contract_to_crm_meta(*args, **kwargs)

    def transition_contract(self, *args: Any, **kwargs: Any) -> Any:
        return cs.transition_contract(*args, **kwargs)

    def start_esign_flow(self, *args: Any, **kwargs: Any) -> Any:
        return cs.start_esign_flow(*args, **kwargs)

    def esign_provider_name(self) -> str:
        return cs.esign_provider_name()

    def handle_esign_webhook(self, *args: Any, **kwargs: Any) -> Any:
        return cs.handle_esign_webhook(*args, **kwargs)

    def get_esign_adapter(self) -> Any:
        return cs.get_esign_adapter()

    def stub_esign_store(self) -> Any:
        return cs.stub_esign_store

    def fadada_fasc_client(self) -> Any:
        return cs.fadada_fasc_client


def get_contract_lifecycle_app_service() -> ContractLifecycleApplicationService:
    global _contract_lifecycle_app_service
    if _contract_lifecycle_app_service is None:
        _contract_lifecycle_app_service = ContractLifecycleApplicationService()
    return _contract_lifecycle_app_service
