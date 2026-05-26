"""FastAPI 路由缺口补齐 batch2 — 聚合入口。

聚合自归档蓝图的端点契约；原 batch2 已按业务域拆分到独立模块，本文件仅做路由聚合。
batch2 的路由已合并到 batch1 的各域模块中，此处直接复用 batch1 的聚合结果。
最终按域彻底拆分待 ``docs/reports/LEGACY_CLEANUP_TRACKING.md`` Phase 2D 推进。
"""

from fastapi import APIRouter

from app.fastapi_routes.legacy_gaps_batch1 import router as batch1_router

router = APIRouter(tags=["legacy-gaps-batch2"])
router.include_router(batch1_router)
