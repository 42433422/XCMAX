"""Stable desktop device identity for mobile relay pairing.

The relay device id is an identity, not a label. It must survive desktop
restarts, port changes, and app updates so the mobile app keeps talking to the
same execution endpoint instead of seeing a new device every time.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from pathlib import Path

from app.utils.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)

_DEVICE_ID_FILENAME = "device_id"
_lock = threading.Lock()
_cached: str | None = None


def _device_id_path() -> Path:
    return Path(get_app_data_dir()) / _DEVICE_ID_FILENAME


def get_stable_device_id() -> str:
    """Return this desktop's stable relay device id.

    ``XCAGI_DEVICE_ID`` is an explicit deployment/test override. If persistence
    fails, the process still returns a non-empty temporary id rather than
    blocking relay registration.
    """
    override = os.environ.get("XCAGI_DEVICE_ID", "").strip()
    if override:
        return override

    global _cached
    with _lock:
        if _cached:
            return _cached

        path = _device_id_path()
        try:
            if path.is_file():
                existing = path.read_text(encoding="utf-8").strip()
                if existing:
                    _cached = existing
                    return _cached
        except OSError:
            logger.warning(
                "failed to read device_id, will try to recreate: %s", path, exc_info=True
            )

        new_id = uuid.uuid4().hex
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_id + "\n", encoding="utf-8")
        except OSError:
            logger.warning(
                "failed to persist device_id, using process-local id: %s", path, exc_info=True
            )
        _cached = new_id
        return _cached
