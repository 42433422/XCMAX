# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOD_DIR = REPO / "mods" / "xcagi-customer-service-bridge"


def test_customer_service_manifest_pages():
    from tests.mod_presence import skip_if_bridge_mod_absent

    skip_if_bridge_mod_absent("xcagi-customer-service-bridge")
    data = json.loads((MOD_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert data.get("config", {}).get("customer_service_pages_via_mod") is True
    assert (MOD_DIR / "frontend" / "routes.js").is_file()


def test_customer_service_mod_init_accepts_manager_call():
    import inspect

    from tests.mod_presence import skip_if_bridge_mod_absent

    skip_if_bridge_mod_absent("xcagi-customer-service-bridge")
    from app.mod_sdk.mods_bus import import_mod_backend_py

    module = import_mod_backend_py(str(MOD_DIR), "xcagi-customer-service-bridge", "blueprints")
    init_fn = module.mod_init
    sig = inspect.signature(init_fn)
    params = list(sig.parameters.values())
    optional = not params or all(p.default is not inspect.Parameter.empty for p in params)
    assert optional, "mod_init must be callable with zero args from ModManager"
    init_fn()
    init_fn(mod_id="xcagi-customer-service-bridge")


def test_list_customer_service_pages_registry():
    from app.mod_sdk.customer_service_pages_compat import list_customer_service_pages_registry

    reg = list_customer_service_pages_registry()
    assert reg.get("page_count") == 2
    assert "/enterprise-customer-service" in reg.get("host_pages", [])
