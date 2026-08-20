# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.approval_workspace_app_service")


from app.application.approval_workspace_app_service_part02_part01 import (
    approve_request as approve_request,
)
from app.application.approval_workspace_app_service_part02_part01 import (
    reject_request as reject_request,
)
from app.application.approval_workspace_app_service_part02_part02 import (
    _normalize_statuses as _normalize_statuses,
)
from app.application.approval_workspace_app_service_part02_part02 import (
    check_approver_orphan as check_approver_orphan,
)
from app.application.approval_workspace_app_service_part02_part02 import (
    create_flow as create_flow,
)
from app.application.approval_workspace_app_service_part02_part02 import (
    delete_request as delete_request,
)
from app.application.approval_workspace_app_service_part02_part02 import (
    get_approval_users as get_approval_users,
)
from app.application.approval_workspace_app_service_part02_part02 import (
    get_flow_detail as get_flow_detail,
)
from app.application.approval_workspace_app_service_part02_part02 import (
    list_flows as list_flows,
)
from app.application.approval_workspace_app_service_part02_part02 import (
    process_approval_timeouts_endpoint as process_approval_timeouts_endpoint,
)
from app.application.approval_workspace_app_service_part02_part02 import (
    withdraw_request as withdraw_request,
)
from app.application.approval_workspace_app_service_part02_part03 import (
    delete_flow as delete_flow,
)
from app.application.approval_workspace_app_service_part02_part03 import (
    toggle_flow_active as toggle_flow_active,
)
from app.application.approval_workspace_app_service_part02_part03 import (
    update_flow as update_flow,
)
