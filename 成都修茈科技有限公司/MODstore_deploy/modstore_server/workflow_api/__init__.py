from fastapi import APIRouter

from modstore_server.workflow_api.crud import router as crud_router
from modstore_server.workflow_api.employee import router as employee_router
from modstore_server.workflow_api.execution import router as execution_router
from modstore_server.workflow_api.hooks import workflow_hooks_router
from modstore_server.workflow_api.nodes import router as nodes_router
from modstore_server.workflow_api.sandbox import router as sandbox_router
from modstore_server.workflow_api.triggers import router as triggers_router
from modstore_server.workflow_api.versions import router as versions_router

router = APIRouter(prefix="/api/workflow", tags=["workflow"])

# Register crud last: its `/{workflow_id}` would otherwise match paths like
# `/employee-eligible` before the dedicated routers.
router.include_router(employee_router)
router.include_router(nodes_router)
router.include_router(execution_router)
router.include_router(sandbox_router)
router.include_router(triggers_router)
router.include_router(versions_router)
router.include_router(crud_router)

__all__ = ["router", "workflow_hooks_router"]
