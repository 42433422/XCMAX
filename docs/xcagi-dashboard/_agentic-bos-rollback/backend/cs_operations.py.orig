"""客服 / 合同 / 运营 / 财务归档 — 遗留实现网关（实现仍在 app.services）。"""

from __future__ import annotations

from typing import Any

# 合同与电子签
from app.services.contract_lifecycle import (  # noqa: F401
    apply_contract_to_crm_meta,
    get_contract_block,
    handle_esign_webhook,
    start_esign_flow,
    transition_contract,
)
from app.services.esign_adapter import (  # noqa: F401
    esign_channel_status,
    esign_provider_name,
    get_esign_adapter,
)
from app.services.fadada_fasc_client import (  # noqa: F401
    parse_fadada_callback_biz,
    verify_fadada_callback_signature,
)
from app.services import stub_esign_store as stub_esign_store  # noqa: F401
from app.services import fadada_fasc_client as fadada_fasc_client  # noqa: F401

# CRM / 管道
from app.services.user_cs_crm_store import (  # noqa: F401
    _connect,
    ensure_crm_schema,
    get_crm_invoice_by_id,
    get_opportunity_by_market_user,
    list_crm_invoices,
)
from app.services.user_cs_pipeline import load_pipeline, save_pipeline  # noqa: F401
from app.services.tax_invoice_provider import issue_crm_invoice_for_pipeline  # noqa: F401
from app.services.finance_unified_archive import (  # noqa: F401
    archive_from_crm_invoice,
    list_ledger,
    rebuild_ledger_archive,
    summarize_ledger,
)
from app.services.user_cs_delivery_signoff import signoff_backend_info  # noqa: F401

# 微信集成
from app.services.wechat_decrypt_autoconfig import (  # noqa: F401
    get_wechat_decrypt_status,
    prepare_wechat_message_db_for_read,
)
from app.services.wechat_decrypt_http import wechat_decrypt_auto_configure_response  # noqa: F401
from app.services.wechat_group_customer_bridge import (  # noqa: F401
    _latest_context_message,
    build_starred_group_feed,
    get_bindings_for_user,
    list_group_contacts,
    save_bindings_for_user,
    sync_bound_groups_from_live_wechat,
    sync_group_messages,
)
from app.services.wechat_passive_group_monitor import (  # noqa: F401
    assert_safe_outbound_group_reply,
    get_passive_poll_config,
    passive_poll_once,
    probe_passive_llm_ready,
    reset_passive_watch,
    save_passive_poll_config,
)

# 运营 / 对账
from app.services.operations_line_bridge import compute_operations_health  # noqa: F401
from app.services.contract_expiry_scheduler import run_contract_expiry_scan  # noqa: F401
from app.services.reconciliation_scheduler import (  # noqa: F401
    get_reconciliation_status,
    run_reconciliation_full_cycle,
    run_reconciliation_preview_cycle,
)
from app.services import reconciliation_scheduler as reconciliation_scheduler  # noqa: F401
from app.services import fhd_payment_reconciliation as fhd_payment_reconciliation  # noqa: F401

# 管理同步
from app.services.admin_sync_service import (  # noqa: F401
    fetch_inbox_row,
    list_sync_conflicts,
    mark_inbox_skipped,
)

__all__ = [
    "apply_contract_to_crm_meta",
    "get_contract_block",
    "handle_esign_webhook",
    "start_esign_flow",
    "transition_contract",
    "esign_channel_status",
    "esign_provider_name",
    "get_esign_adapter",
    "parse_fadada_callback_biz",
    "verify_fadada_callback_signature",
    "stub_esign_store",
    "fadada_fasc_client",
    "_connect",
    "ensure_crm_schema",
    "get_crm_invoice_by_id",
    "get_opportunity_by_market_user",
    "list_crm_invoices",
    "load_pipeline",
    "save_pipeline",
    "issue_crm_invoice_for_pipeline",
    "archive_from_crm_invoice",
    "list_ledger",
    "rebuild_ledger_archive",
    "summarize_ledger",
    "signoff_backend_info",
    "get_wechat_decrypt_status",
    "prepare_wechat_message_db_for_read",
    "wechat_decrypt_auto_configure_response",
    "_latest_context_message",
    "build_starred_group_feed",
    "get_bindings_for_user",
    "list_group_contacts",
    "save_bindings_for_user",
    "sync_bound_groups_from_live_wechat",
    "sync_group_messages",
    "assert_safe_outbound_group_reply",
    "get_passive_poll_config",
    "passive_poll_once",
    "probe_passive_llm_ready",
    "reset_passive_watch",
    "save_passive_poll_config",
    "compute_operations_health",
    "run_contract_expiry_scan",
    "get_reconciliation_status",
    "run_reconciliation_full_cycle",
    "run_reconciliation_preview_cycle",
    "reconciliation_scheduler",
    "fhd_payment_reconciliation",
    "list_sync_conflicts",
    "fetch_inbox_row",
    "mark_inbox_skipped",
    "wechat_group_customer_bridge_module",
]


def wechat_group_customer_bridge_module() -> Any:
    """返回 ``wechat_group_customer_bridge`` 模块（供应用层按模块访问扩展 API）。"""
    import app.services.wechat_group_customer_bridge as bridge

    return bridge
