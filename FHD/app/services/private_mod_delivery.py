"""客户私有交付服务的稳定兼容入口。

实现按状态、流程推进与产物安装拆分；调用方继续从本模块导入，避免跨层扩散。
"""

from app.services import private_mod_delivery_state as _state
from app.services.private_mod_delivery_artifacts import (
    custom_delivery_remote_json,
    fetch_private_mod_library,
    install_custom_delivery_artifact,
    is_newer_version,
    update_private_mod_from_library,
    version_key,
)
from app.services.private_mod_delivery_progress import (
    attach_track_nodes,
    overall_status,
    set_node_status,
    set_track_status,
    stage_label,
)
from app.services.private_mod_delivery_state import (
    HAPPY_PATH,
    STAGE_GOALS,
    STAGE_LABELS,
    STAGE_TRANSITIONS,
    STAGES,
    TRACKS,
    account_projects,
    account_scope,
    allowed_next_stages,
    apply_account_state,
    assert_stage_transition,
    export_account_state,
    load_stage_flow_from_ssot,
    merge_orphan_local_delivery_into_market,
    normalize_track,
    project_state,
    stage_goal,
)

_state_path = _state._state_path
_account_projects = account_projects
_apply_account_state = apply_account_state
_export_account_state = export_account_state
_merge_orphan_local_delivery_into_market = merge_orphan_local_delivery_into_market
_project_state = project_state
_set_node_status = set_node_status
_set_track_status = set_track_status


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
