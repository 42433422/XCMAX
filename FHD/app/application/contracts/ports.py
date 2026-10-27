"""Facade re-export of application feature protocols (debt19)."""

from __future__ import annotations

import importlib

_m = importlib.import_module("app.application.admin_control.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.aiopen.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.approval_workspace.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.customer_service.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.desktop_relay.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.employee_tools.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.group_chat.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.knowledge.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.market_bridge.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.market_llm.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.mobile_extensions.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.mod_store.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.planner_compat.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.shipment_etl.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.super_employee.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)

_m = importlib.import_module("app.application.user_memory.protocols")
globals().update(
    {
        k: getattr(_m, k)
        for k in getattr(_m, "__all__", [x for x in dir(_m) if not x.startswith("_")])
    }
)
