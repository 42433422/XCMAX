"""企业版通用 ETL 应用层。"""

from app.application.etl.service import EtlService, get_etl_service

__all__ = ["EtlService", "get_etl_service"]
