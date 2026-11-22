"""Bind enterprise source reads to the active authorized tenant and Mod."""

from dataclasses import dataclass

from app.infrastructure.tenant_scope import current_tenant_id
from app.request_active_mod_ctx import get_request_active_mod_id


@dataclass(frozen=True)
class SourceScope:
    tenant_id: int
    actor_id: str
    mod_id: str = ""

    def validate(self) -> None:
        if self.tenant_id <= 0 or not self.actor_id.isdigit() or int(self.actor_id) <= 0:
            raise PermissionError("enterprise_identity_required")
        ambient = current_tenant_id()
        if ambient is not None and ambient != self.tenant_id:
            raise PermissionError("enterprise_tenant_mismatch")
        if self.mod_id != get_request_active_mod_id():
            raise PermissionError("enterprise_mod_mismatch")
