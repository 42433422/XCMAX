import logging

from app.di.registry import get_service_registry
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def get_customers_session():
    """返回一个与全局 ``app.db.SessionLocal`` 同源的 session。

    历史上本模块维护独立的 ``_customers_engine``，容易绕过 ``ModContextMiddleware``
    导致客户/购买单位数据始终落在基库。现在统一走 ``app.db`` 的 mod-aware 引擎，
    请求头 ``X-XCAGI-Active-Mod-Id`` 会自动把 URL 改写成 ``xcagi__<mod>``
    （或 ``products__<mod>.db``），与 ``SQLAlchemyCustomerRepository`` 一致。

    里程碑 L++：安装 ERP 门面 Mod 且 ``repository_via_mod`` 时经 Mod 适配器解析。
    """
    try:
        from app.mod_sdk.erp_repository_registry import resolve_customers_session

        return resolve_customers_session()
    except RECOVERABLE_ERRORS:
        logger.debug("resolve_customers_session fallback to host SessionLocal", exc_info=True)
    from app.db import SessionLocal

    return SessionLocal()


def reset_customers_engine() -> None:
    """为向下兼容保留的空实现。

    历史上 ``dispose_and_recreate_engine`` 会在重建全局引擎时调用这里清 customer
    侧的独立缓存。迁移到统一 engine 后，重置工作完全由 ``app.db`` 内部完成，这里
    仅保留符号以便现有 ``try/except import`` 调用链不中断。
    """
    get_service_registry().invalidate_customer_application_service()



from app.application.customer_crud_mixin import CustomerCrudMixin
from app.application.customer_relationship_mixin import CustomerRelationshipMixin
from app.application.customer_transfer_mixin import CustomerTransferMixin


class CustomerApplicationService(
    CustomerCrudMixin, CustomerTransferMixin, CustomerRelationshipMixin
):
    """客户应用服务：组合客户 CRUD、导入导出及关系管理能力。"""

    def __init__(self):
        pass

    @property
    def _engine(self):
        """保留旧属性以兼容外部读取；实际返回 ``app.db`` 的全局 engine 代理。"""
        from app.db import engine

        return engine

    @property
    def _SessionLocal(self):
        """返回可调用的 SessionLocal；与 ``app.db.SessionLocal`` 同一入口。"""
        from app.db import SessionLocal

        return SessionLocal

    def _get_session(self):
        return get_customers_session()


from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

instrument_application_service_class(CustomerApplicationService)


def get_customer_app_service() -> CustomerApplicationService:
    """获取客户服务单例"""
    return get_service_registry().customer_application_service
