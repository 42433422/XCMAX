# ruff: noqa: E402, F401, I001

"""内部构建 release_train SSOT；对外稳定产品版本始终由 FHD/VERSION.md 管理。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from modstore_server.release_train_digest import (
    attach_release_train_to_digest,
)
from modstore_server.release_train_digest import (
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

from modstore_server.release_train_merged import (
    _digest_calendar_day as _digest_calendar_day,
)
from modstore_server.release_train_merged import (
    _snapshot_state_to_history as _snapshot_state_to_history,
)
from modstore_server.release_train_merged import (
    active_backup_guard as active_backup_guard,
)
from modstore_server.release_train_merged import (
    bump_release_train as bump_release_train,
)
from modstore_server.release_train_merged import (
    clear_backup_guard as clear_backup_guard,
)
from modstore_server.release_train_merged import default_state as default_state
from modstore_server.release_train_merged import history_dir as history_dir
from modstore_server.release_train_merged import (
    list_release_train_history as list_release_train_history,
)
from modstore_server.release_train_merged import load_state as load_state
from modstore_server.release_train_merged import (
    mark_backup_guard_probe_escalated as mark_backup_guard_probe_escalated,
)
from modstore_server.release_train_merged import (
    record_backup_guard_probe_attempt as record_backup_guard_probe_attempt,
)
from modstore_server.release_train_merged import (
    release_train_context_for_digest as release_train_context_for_digest,
)
from modstore_server.release_train_merged import (
    rollback_release_train as rollback_release_train,
)
from modstore_server.release_train_merged import save_state as save_state
from modstore_server.release_train_merged import set_backup_guard as set_backup_guard
from modstore_server.release_train_merged import snapshot_public as snapshot_public
from modstore_server.release_train_merged import ssot_path as ssot_path

__all__ = ["format_quad", "parse_quad"]
