"""import_mod_backend_py 按物理路径隔离 sys.modules 缓存。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ADMIN_MOD = REPO / "mods-admin-runtime" / "xcagi-erp-domain-bridge"
SSOT_MOD = REPO / "mods" / "xcagi-erp-domain-bridge"
MOD_ID = "xcagi-erp-domain-bridge"
STEM = "domain_handlers"


@pytest.fixture(autouse=True)
def _purge_cached_modules():
    to_drop = [k for k in sys.modules if k.startswith("_xcagi_mod_") and STEM in k]
    for k in to_drop:
        sys.modules.pop(k, None)
    yield
    for k in to_drop:
        sys.modules.pop(k, None)


def test_same_mod_id_different_paths_load_distinct_modules():
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    if not ADMIN_MOD.is_dir() or not SSOT_MOD.is_dir():
        pytest.skip("erp bridge mods not present")
    a = import_mod_backend_py(str(ADMIN_MOD), MOD_ID, STEM)
    b = import_mod_backend_py(str(SSOT_MOD), MOD_ID, STEM)
    assert a is not b
    assert a.__name__ != b.__name__
    # mods SSOT 版 shipment 走 core service；admin-runtime 走 get_shipment_app_service
    src_a = Path(a.__file__).resolve()
    src_b = Path(b.__file__).resolve()
    assert src_a != src_b
