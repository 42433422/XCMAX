"""
Example Mod — FastAPI 路由 only（无 Flask）。
"""

import logging

logger = logging.getLogger(__name__)


def register_fastapi_routes(app, mod_id: str) -> None:
    """主进程 FastAPI：与历史蓝图相同路径。"""
    from fastapi import APIRouter

    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"mod-{mod_id}"])

    @router.get("/hello")
    def hello():
        return {
            "success": True,
            "data": {
                "message": f"Hello from {mod_id}!",
                "version": "1.0.0",
            },
        }

    @router.get("/status")
    def status():
        return {"success": True, "data": {"mod_id": mod_id, "status": "running"}}

    app.include_router(router)
    logger.info("Example mod FastAPI routes registered for: %s", mod_id)


def _comms_ping(*args, **kwargs):
    """供其他 Mod 通过 get_mod_comms().call(..., 'example-mod', 'ping', ...) 调用。"""
    from app.mod_sdk.comms import get_caller_mod_id

    return {
        "pong": True,
        "mod": "example-mod",
        "caller": get_caller_mod_id(),
        "args": args,
        "kwargs": kwargs,
    }


def mod_init():
    logger.info("Example mod initialized")
    try:
        from app.mod_sdk.comms import get_mod_comms

        get_mod_comms().register("example-mod", "ping", _comms_ping, replace=True)
    except Exception as e:
        logger.warning("example-mod comms register skipped: %s", e)
