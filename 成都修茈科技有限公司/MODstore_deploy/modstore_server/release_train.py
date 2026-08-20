# ruff: noqa: E402, F401, I001
"""内部构建 release_train SSOT；对外稳定产品版本始终由 FHD/VERSION.md 管理。"""

# isort: skip_file

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from modstore_server.release_train_digest import (
    attach_release_train_to_digest,
    release_train_context_for_digest as _release_train_context_for_digest,
)
from modstore_server.release_train_history import list_history
from modstore_server.release_train_versions import (
    bump_daily,
    bump_quad,
    classify_release_kind,
    decennial_generation,
    decennial_generation_label,
    format_quad,
    is_installer_day,
    is_major_day,
    next_decennial_anchor,
    parse_quad,
)

logger = logging.getLogger(__name__)

__all__ = [
    "format_quad",
    "parse_quad",
]


from modstore_server.release_train_part01 import (
    ssot_path as ssot_path,
    default_state as default_state,
    history_dir as history_dir,
    _snapshot_state_to_history as _snapshot_state_to_history,
    _digest_calendar_day as _digest_calendar_day,
    load_state as load_state,
    save_state as save_state,
    snapshot_public as snapshot_public,
    set_backup_guard as set_backup_guard,
    clear_backup_guard as clear_backup_guard,
    active_backup_guard as active_backup_guard,
    record_backup_guard_probe_attempt as record_backup_guard_probe_attempt,
    mark_backup_guard_probe_escalated as mark_backup_guard_probe_escalated,
    bump_release_train as bump_release_train,
    list_release_train_history as list_release_train_history,
    rollback_release_train as rollback_release_train,
    release_train_context_for_digest as release_train_context_for_digest,
)
