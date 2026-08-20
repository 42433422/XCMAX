"""Hybrid runtime: config-layer first, optional code-layer fallback."""

from __future__ import annotations

from typing import Any

from .._internals import TriggerPolicy
from .runtime import CodeSkillRuntime


class HybridSkillRuntime:
    """Dispatch by `ESkill.skill_type`: config | code | hybrid."""

    def __init__(
        self,
        config_runtime: Any,
        code_runtime: CodeSkillRuntime,
        *,
        config_store: Any | None = None,
    ):
        self.config_runtime = config_runtime
        self.code_runtime = code_runtime
        self.config_store = config_store or config_runtime.store

    def run(
        self,
        skill_id: str,
        input_data: dict[str, Any],
        *,
        trigger_policy: TriggerPolicy | None = None,
        quality_gate: dict[str, Any] | None = None,
        force_dynamic: bool = False,
        solidify: bool = True,
    ) -> Any:
        skill = self.config_store.get_skill(skill_id)
        st = getattr(skill, "skill_type", None) or "config"

        if st == "config":
            return self.config_runtime.run(
                skill_id,
                input_data,
                trigger_policy=trigger_policy,
                quality_gate=quality_gate,
                force_dynamic=force_dynamic,
                solidify=solidify,
            )

        if st == "code":
            return self.code_runtime.run(
                skill_id,
                input_data,
                force_dynamic=force_dynamic,
                solidify=solidify,
                trigger_policy=trigger_policy,
                quality_gate=quality_gate,
            )
        # hybrid
        r1 = self.config_runtime.run(
            skill_id,
            input_data,
            trigger_policy=trigger_policy,
            quality_gate=quality_gate,
            force_dynamic=force_dynamic,
            solidify=solidify,
        )
        if r1.stage in ("static", "solidified"):
            return r1

        return self.code_runtime.run(
            skill_id,
            input_data,
            solidify=solidify,
            trigger_policy=trigger_policy,
            quality_gate=quality_gate,
        )
