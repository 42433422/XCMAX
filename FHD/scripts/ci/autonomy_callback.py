"""兼容 shim：转发到 scripts/autonomy/autonomy_callback.py（SSOT）。

历史路径 ``scripts/ci/autonomy_callback`` 仍可 import；实现已合并到 autonomy 包。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SSOT = Path(__file__).resolve().parents[1] / "autonomy" / "autonomy_callback.py"
_spec = importlib.util.spec_from_file_location("xcagi_autonomy_callback_ssot", _SSOT)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load autonomy callback SSOT from {_SSOT}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

autonomy_callback = _mod.autonomy_callback
report_callback = _mod.report_callback
deploy_callback = _mod.deploy_callback
report_executed = _mod.report_executed
report_execution_failed = _mod.report_execution_failed
report_rejected = _mod.report_rejected
report_approval_requested = _mod.report_approval_requested

__all__ = list(_mod.__all__)
