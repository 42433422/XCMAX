# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.workflow_engine")


from modstore_server.workflow_engine_workflowengine_mixin01__workflowenginepart01mixin_mixin01 import (
    __WorkflowEnginePart01MixinPart01Mixin,
)
from modstore_server.workflow_engine_workflowengine_mixin01__workflowenginepart01mixin_mixin02 import (
    __WorkflowEnginePart01MixinPart02Mixin,
)


class _WorkflowEnginePart01Mixin(
    __WorkflowEnginePart01MixinPart01Mixin, __WorkflowEnginePart01MixinPart02Mixin
):
    pass
