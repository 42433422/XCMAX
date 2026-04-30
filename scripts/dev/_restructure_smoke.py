"""Post-restructure smoke test.

Run from repo root:
    cd XCAGI && python ../scripts/dev/_restructure_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo root is 2 up from this file
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))


def main() -> int:
    from app.fastapi_app import get_fastapi_app

    app = get_fastapi_app()
    routes = list(app.routes)
    print(f"[ok] FastAPI app factory constructed; routes = {len(routes)}")

    from app.infrastructure.payment import alipay, order_store  # noqa: F401

    print("[ok] app.infrastructure.payment imports resolved")

    paths = {getattr(r, "path", "") for r in routes}
    probes = [
        "/api/health",
        "/api/ai/chat",
        "/api/model-payment/plans",
        "/api/shipment/create",
        "/api/mp/v1/auth/login",
    ]
    missing = []
    for p in probes:
        hit = any(rp == p or rp.startswith(p + "/") for rp in paths)
        status = "FOUND" if hit else "MISSING"
        print(f"  {p}: {status}")
        if not hit:
            missing.append(p)

    if missing:
        print(f"[fail] {len(missing)} endpoint probes missing: {missing}")
        return 1
    print("[done] smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
