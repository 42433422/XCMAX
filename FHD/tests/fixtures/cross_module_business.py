"""Synthetic business workbook shared by cross-module acceptance and HTTP tests."""

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.application.elt.targets.products import ProductAdapter
from app.db.models.product import Product
from app.domain.task_lifecycle.control import SessionBook
from app.infrastructure.tenant_scope import current_tenant_id


def _build_source_workbook(path: Path, *, rows: list[list[str]] | None = None) -> None:
    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet.title = "发货明细"
    sheet.append(["购买单位", "型号", "产品名称", "规格", "价格"])
    for row in (
        rows
        if rows is not None
        else [
            ["  华东涂料  ", "HX-1", " 内墙底漆 ", "20kg", "12.50"],
            ["华东涂料", "HX-2", "外墙面漆", "18kg", "30"],
            ["华东涂料", "HX-BAD", "", "10kg", "9"],
            ["华东涂料", "HX-NEG", "负价样品", "1kg", "-3"],
            ["合计", "", "", "", ""],
        ]
    ):
        sheet.append(row)
    notes = workbook.create_sheet("说明")
    notes.append(["本表是说明区域，不参与导入"])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()


def interpret_business_intent(
    message: str,
    *,
    file_name: str | None = None,
    prior_goal: str | None = None,
) -> dict[str, Any]:
    """Deterministic intent for this business loop. Ambiguous text does not select a write."""
    text_value = str(message or "").strip()
    inherited = str(prior_goal or "").strip()
    if text_value in {"继续", "接着", "按上次的做"} and inherited:
        text_value = inherited
        inherited_from_prior = True
    else:
        inherited_from_prior = False
    has_file = bool(file_name)
    asks_import = any(token in text_value for token in ("导入", "写入", "ERP", "产品库"))
    asks_excel = any(token in text_value for token in ("Excel", "表格", "切片", "清洗"))
    asks_mod = any(token in text_value for token in ("MOD", "员工", "后续"))
    if not text_value or (asks_import and not has_file and not inherited_from_prior):
        return {
            "complete": False,
            "question": "请提供要处理的业务 Excel，并说明要写入的 ERP 区域。",
            "tool_calls": [],
            "goal": "",
        }
    if text_value in {"处理一下", "帮我处理", "看看这个"} and not (asks_import or asks_excel):
        return {
            "complete": False,
            "question": "目标不明确。需要确认是只核对表格，还是写入 ERP。未确认前不会执行高风险写入。",
            "tool_calls": [],
            "goal": "",
            "rejected_high_risk": True,
        }
    tools = ["excel_analysis.read", "elt.parse_file"]
    if asks_import:
        tools.append("products.batch_create")
    if asks_mod:
        tools.append("excel-full-read-employee")
    return {
        "complete": True,
        "goal": text_value,
        "inputs": {"file_name": file_name, "inherited": inherited_from_prior},
        "outputs": ["result.xlsx", "anomaly_list"],
        "rules": ["合格行才写入产品库", "原件不得修改", "异常行必须单独列出"],
        "constraints": ["敏感写入必须审批", "成功标记不能代替复核"],
        "tool_match": tools,
        "useless_tools_omitted": ["products.delete", "products.batch_delete"],
        "tool_calls_planned": tools,
    }


def _product_count(db: Session, unit: str) -> int:
    return int(db.query(Product).filter(Product.unit == unit).count())


def update_product_price(
    db: Session, *, unit: str, model_number: str, price: str
) -> dict[str, Any]:
    adapter = ProductAdapter()
    current = (
        db.query(Product).filter(Product.unit == unit, Product.model_number == model_number).one()
    )
    before = str(current.price)
    data = {
        "unit": unit,
        "model_number": model_number,
        "name": current.name,
        "price": price,
        "specification": current.specification,
    }
    decision = adapter.preview(db, data, allowed_update_fields={"price"}, context={})
    if decision.action != "update":
        return {"success": False, "message": decision.reason or decision.action, "before": before}
    result = adapter.execute_row(
        db,
        data,
        action="update",
        match_ref=str(decision.match_ref),
        allowed_update_fields={"price"},
        context={},
    )
    db.commit()
    refreshed = (
        db.query(Product).filter(Product.unit == unit, Product.model_number == model_number).one()
    )
    return {
        "success": True,
        "before": before,
        "after": str(refreshed.price),
        "match_ref": result["match_ref"],
        "stored_after": result["after"].get("price"),
    }


def _delivery_row(db: Session, key: str) -> dict[str, Any] | None:
    body = SessionBook(db).get("cross_module_acceptance", str(current_tenant_id()), key)
    payload = body.get("delivery")
    return payload if isinstance(payload, dict) else None


def _save_delivery(db: Session, key: str, payload: dict[str, Any]) -> None:
    SessionBook(db).put(
        "cross_module_acceptance", str(current_tenant_id()), key, {"delivery": payload}
    )
    db.commit()
