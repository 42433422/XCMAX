"""
FastAPI 生命周期集成

NeuroBus 与 FastAPI 生命周期绑定
- 启动时初始化
- 关闭时清理
- 健康检查
"""

import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI

from app.neuro_bus.bus_setup import (
    setup_neuro_bus,
    teardown_neuro_bus,
    get_neuro_bus_manager,
)
from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.domains.base import get_domain_registry
from app.domain.neuro.processors.coordinator import get_processor_coordinator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def setup_neurobus_lifespan(app: FastAPI):
    """
    NeuroBus 生命周期管理器
    
    用法:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            async with setup_neurobus_lifespan(app):
                # 其他初始化
                yield
        
        app = FastAPI(lifespan=lifespan)
    """
    logger.info("NeuroBus: Starting initialization...")
    
    try:
        # 1. 启动核心总线
        await setup_neuro_bus()
        logger.info("NeuroBus core started")
        
        # 2. 初始化所有领域
        domain_registry = get_domain_registry()
        await domain_registry.initialize_all()
        logger.info(f"NeuroDomains initialized: {domain_registry.list_domains()}")
        
        # 3. 启动处理器
        processor = get_processor_coordinator()
        # ProcessorCoordinator 是无状态的，无需显式启动
        logger.info("ProcessorCoordinator ready")
        
        # 4. 注册到应用状态
        manager = get_neuro_bus_manager()
        app.state.neuro_bus_manager = manager
        
        logger.info("NeuroBus: Ready for events")
        
        yield
        
    finally:
        logger.info("NeuroBus: Starting shutdown...")
        
        try:
            # 1. 关闭所有领域
            domain_registry = get_domain_registry()
            await domain_registry.shutdown_all()
            logger.info("NeuroDomains shutdown")
            
            # 2. 关闭总线
            await teardown_neuro_bus()
            logger.info("NeuroBus core stopped")
            
        except Exception as e:
            logger.exception(f"NeuroBus shutdown error: {e}")
        
        logger.info("NeuroBus: Shutdown complete")


def get_neurobus_health() -> Dict[str, Any]:
    """
    获取 NeuroBus 健康状态
    
    用于健康检查端点
    """
    try:
        manager = get_neuro_bus_manager()
        bus = get_neuro_bus()
        
        health = manager.get_health()
        
        # 添加各组件状态
        health["components"] = {
            "bus_running": bool(bus and bus.is_running),
            "queue_size": bus.get_stats().get("queue_size", 0) if bus else 0,
            "domains": get_domain_registry().list_domains(),
        }
        
        # 添加处理器统计
        try:
            processor = get_processor_coordinator()
            health["processors"] = processor.get_all_processor_stats()
        except Exception:
            pass
        
        return health
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


# 便捷函数

def add_neurobus_routes(app: FastAPI):
    """
    添加 NeuroBus 相关路由
    
    添加以下端点：
    - GET /api/neurobus/health - 健康检查
    - GET /api/neurobus/stats - 统计数据
    """
    
    @app.get("/api/neurobus/health")
    async def neurobus_health():
        return get_neurobus_health()
    
    @app.get("/api/neurobus/stats")
    async def neurobus_stats():
        try:
            processor = get_processor_coordinator()
            return processor.get_all_processor_stats()
        except Exception as e:
            return {"error": str(e)}
    
    logger.info("NeuroBus routes added")


def create_fastapi_app_with_neurobus(
    title: str = "XCAGI with Neuro-DDD",
    **kwargs
) -> FastAPI:
    """
    创建带 NeuroBus 集成的 FastAPI 应用
    
    这是一个工厂函数，创建预配置 NeuroBus 的 FastAPI 应用
    """
    @asynccontextmanager
    async def combined_lifespan(app: FastAPI):
        # NeuroBus 生命周期
        async with setup_neurobus_lifespan(app):
            # 应用特定的生命周期
            if "lifespan" in kwargs:
                async with kwargs["lifespan"](app):
                    yield
            else:
                yield
    
    # 创建应用
    app = FastAPI(
        title=title,
        lifespan=combined_lifespan,
        **{k: v for k, v in kwargs.items() if k != "lifespan"}
    )
    
    # 添加路由
    add_neurobus_routes(app)
    
    return app
