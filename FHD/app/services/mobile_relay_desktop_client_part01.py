# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.mobile_relay_desktop_client")


from app.services.mobile_relay_desktop_client_part01_part01 import (
    _api_url as _api_url,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    _ensure_super_employee_service_classes as _ensure_super_employee_service_classes,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    _gc_orphan_workspaces as _gc_orphan_workspaces,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    _max_concurrent as _max_concurrent,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    _migrate_legacy_config_once as _migrate_legacy_config_once,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    _public_payload_from_config as _public_payload_from_config,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    _read_config as _read_config,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    _relay_base_url as _relay_base_url,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    _relay_http_client as _relay_http_client,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    _relay_poll_backoff_seconds as _relay_poll_backoff_seconds,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    _write_config as _write_config,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    cached_desktop_relay_payload as cached_desktop_relay_payload,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    register_desktop_relay as register_desktop_relay,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    start_desktop_relay_poller as start_desktop_relay_poller,
)
from app.services.mobile_relay_desktop_client_part01_part01 import (
    stop_desktop_relay_poller as stop_desktop_relay_poller,
)
from app.services.mobile_relay_desktop_client_part01_part02 import (
    _complete_relay_task as _complete_relay_task,
)
from app.services.mobile_relay_desktop_client_part01_part02 import (
    _extract_tool_calls as _extract_tool_calls,
)
from app.services.mobile_relay_desktop_client_part01_part02 import (
    _poll_loop as _poll_loop,
)
from app.services.mobile_relay_desktop_client_part01_part02 import (
    _poll_once as _poll_once,
)
