"""客户私有交付的应用层用例边界。"""

from app.application import private_mod_delivery_state as _state
from app.application.private_mod_delivery_artifacts import (
    custom_delivery_remote_json as _custom_delivery_remote_json,
)
from app.application.private_mod_delivery_artifacts import (
    fetch_private_mod_library,
    install_custom_delivery_artifact,
    is_newer_version,
    update_private_mod_from_library,
    version_key,
)
from app.application.private_mod_delivery_progress import (
    attach_track_nodes,
    overall_status,
    stage_label,
)
from app.application.private_mod_delivery_progress import (
    set_node_status as _set_node_status,
)
from app.application.private_mod_delivery_progress import (
    set_track_status as _set_track_status,
)
from app.application.private_mod_delivery_state import (
    HAPPY_PATH,
    STAGE_GOALS,
    STAGE_LABELS,
    STAGE_TRANSITIONS,
    STAGES,
    TRACKS,
    account_scope,
    allowed_next_stages,
    assert_stage_transition,
    load_stage_flow_from_ssot,
    normalize_track,
    stage_goal,
)
from app.application.private_mod_delivery_state import (
    account_projects as _account_projects,
)
from app.application.private_mod_delivery_state import (
    apply_account_state as _apply_account_state,
)
from app.application.private_mod_delivery_state import (
    export_account_state as _export_account_state,
)
from app.application.private_mod_delivery_state import (
    merge_orphan_local_delivery_into_market as _merge_orphan_local_delivery_into_market,
)
from app.application.private_mod_delivery_state import (
    project_state as _project_state,
)

# 测试与桌面迁移仍可替换这一稳定入口；实际状态函数位于应用层内部模块。
_state_path = _state._state_path


def _sync_compat_state_path() -> None:
    _state._state_path = _state_path


def project_state(*args, **kwargs):
    _sync_compat_state_path()
    return _project_state(*args, **kwargs)


def account_projects(*args, **kwargs):
    _sync_compat_state_path()
    return _account_projects(*args, **kwargs)


def export_account_state(*args, **kwargs):
    _sync_compat_state_path()
    return _export_account_state(*args, **kwargs)


def apply_account_state(*args, **kwargs):
    _sync_compat_state_path()
    return _apply_account_state(*args, **kwargs)


def merge_orphan_local_delivery_into_market(*args, **kwargs):
    _sync_compat_state_path()
    return _merge_orphan_local_delivery_into_market(*args, **kwargs)


def set_node_status(*args, **kwargs):
    _sync_compat_state_path()
    return _set_node_status(*args, **kwargs)


def set_track_status(*args, **kwargs):
    _sync_compat_state_path()
    return _set_track_status(*args, **kwargs)


async def custom_delivery_remote_json(*args, **kwargs):
    return await _custom_delivery_remote_json(*args, **kwargs)


__all__ = [
    "HAPPY_PATH",
    "STAGES",
    "STAGE_GOALS",
    "STAGE_LABELS",
    "STAGE_TRANSITIONS",
    "TRACKS",
    "account_projects",
    "account_scope",
    "allowed_next_stages",
    "apply_account_state",
    "assert_stage_transition",
    "attach_track_nodes",
    "custom_delivery_remote_json",
    "export_account_state",
    "fetch_private_mod_library",
    "install_custom_delivery_artifact",
    "is_newer_version",
    "load_stage_flow_from_ssot",
    "merge_orphan_local_delivery_into_market",
    "normalize_track",
    "overall_status",
    "project_state",
    "set_node_status",
    "set_track_status",
    "stage_goal",
    "stage_label",
    "update_private_mod_from_library",
    "version_key",
]
