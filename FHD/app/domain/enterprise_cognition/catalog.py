"""Enterprise references name existing authorities; they never allocate business IDs."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EntityDefinition:
    entity_type: str
    source: str
    id_field: str
    permission: str
    description: str
    ttl_seconds: int = 30


_DEFINITIONS = (
    EntityDefinition("order", "sales_orders", "id", "tool.sales.query", "销售订单；单号是显示编号"),
    EntityDefinition("supplier", "suppliers", "id", "tool.purchase.query_suppliers", "供应商；不包含联系信息"),
    EntityDefinition(
        "purchase_order",
        "purchase_orders",
        "id",
        "tool.purchase.query_orders",
        "采购订单及分项收货数量；不推断应付或现金余额",
    ),
    EntityDefinition(
        "purchase_inbound",
        "purchase_inbounds",
        "id",
        "tool.purchase.query_inbounds",
        "采购入库凭证及分项数量；不等同库存当前可用量",
    ),
    EntityDefinition(
        "customer",
        "customers",
        "id",
        "customer.view",
        "销售订单关联客户；不等同购买单位",
    ),
    EntityDefinition(
        "employee",
        "ai_employee_profiles",
        "employee_id",
        "employee.list",
        "当前主体拥有的AI员工身份；不等同全局编制",
    ),
    EntityDefinition(
        "task",
        "agent_tasks",
        "task_id",
        "",
        "当前主体的统一任务；执行尝试由active_run_id关联",
    ),
    EntityDefinition(
        "inventory",
        "inventory_transactions",
        "id",
        "tool.inventory.query_transactions",
        "库存流水；仅证明该次变动和前后数量，不等同当前库存余额",
    ),
    EntityDefinition(
        "production",
        "manufacturing_orders",
        "id",
        "tool.mrp.query_orders",
        "生产工单及领料记录；不推断产能或完工率",
    ),
    EntityDefinition(
        "journal_entry",
        "journal_entries",
        "id",
        "tool.finance.ledger_query",
        "原总账凭证、借贷明细与冲销来源；不推断现金、应收或应付余额",
    ),
    EntityDefinition(
        "fund",
        "financial_transactions",
        "id",
        "tool.finance.ledger_query",
        "财务流水；不推断现金或可用余额",
    ),
)
ENTITY_DEFINITIONS = {item.entity_type: item for item in _DEFINITIONS}


def entity_catalog() -> list[dict]:
    return [
        {
            **asdict(item),
            "unique_scope": [
                "tenant_id",
                "actor_id",
                "mod_id",
                "entity_type",
                "entity_id",
            ],
            "read_only": True,
        }
        for item in _DEFINITIONS
    ]


def definition_for(entity_type: str) -> EntityDefinition:
    try:
        return ENTITY_DEFINITIONS[entity_type]
    except KeyError as exc:
        raise ValueError("unsupported_enterprise_entity") from exc
