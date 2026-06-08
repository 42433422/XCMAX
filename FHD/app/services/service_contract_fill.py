"""服务合同字段填充与 docx 生成（桌面本地栈）。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.user_cs_pipeline import _pipeline_roots, load_pipeline

logger = logging.getLogger(__name__)

FIELD_SCHEMA: list[dict[str, str]] = [
    {"key": "party_a_name", "label": "甲方名称", "type": "text"},
    {"key": "party_a_credit_code", "label": "甲方统一社会信用代码", "type": "text"},
    {"key": "total_amount_number", "label": "合同金额（元）", "type": "text"},
    {"key": "expected_out_trade_no", "label": "关联订单号", "type": "text"},
    {"key": "sign_date", "label": "签署日期", "type": "date"},
    {"key": "main_function_list", "label": "主要功能清单", "type": "textarea"},
]


def _overrides_root() -> Path:
    root = _pipeline_roots()[0].parent / "user_cs_contract_fields"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _overrides_file(market_user_id: int) -> Path:
    return _overrides_root() / f"{int(market_user_id)}.json"


def list_field_schema() -> list[dict[str, str]]:
    return list(FIELD_SCHEMA)


def load_field_overrides(market_user_id: int) -> dict[str, Any]:
    path = _overrides_file(market_user_id)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_field_overrides(
    market_user_id: int,
    values: dict[str, Any],
    *,
    username: str = "",
) -> dict[str, Any]:
    _ = username
    path = _overrides_file(market_user_id)
    data = {k: str(v) for k, v in values.items() if v is not None}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return data


def build_merged_fields(market_user_id: int, *, username: str = "") -> dict[str, str]:
    doc = load_pipeline(int(market_user_id), username=username)
    overrides = load_field_overrides(int(market_user_id))
    stored = doc.get("contract_fields") if isinstance(doc.get("contract_fields"), dict) else {}
    merged: dict[str, str] = {}
    for field in FIELD_SCHEMA:
        key = field["key"]
        merged[key] = str(overrides.get(key) or stored.get(key) or "")
    if not merged.get("party_a_name"):
        merged["party_a_name"] = str(doc.get("erp_customer_name") or doc.get("username") or username or "")
    if not merged.get("sign_date"):
        merged["sign_date"] = datetime.now(timezone.utc).date().isoformat()
    return merged


def generated_contracts_dir() -> Path:
    root = _pipeline_roots()[0].parent / "user_cs_contracts" / "generated"
    root.mkdir(parents=True, exist_ok=True)
    return root


def contract_assets_dir() -> Path:
    root = _pipeline_roots()[0].parent / "user_cs_contracts" / "assets"
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_contract_wechat_hint(party_a_name: str, filename: str) -> str:
    name = party_a_name.strip() or "客户"
    file = filename.strip() or "合同.docx"
    return f"{name}，服务合同草案已生成（{file}），请查收并确认条款。"


def generate_contract_docx(
    market_user_id: int,
    *,
    username: str = "",
    field_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = field_values or build_merged_fields(int(market_user_id), username=username)
    party_a = str(values.get("party_a_name") or username or f"客户{market_user_id}")
    amount = str(values.get("total_amount_number") or "")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"contract_{int(market_user_id)}_{stamp}.docx"
    path = generated_contracts_dir() / filename
    # 最小占位：写入 UTF-8 文本文件并改扩展名供下载链路；完整 docx 模板后续可替换
    body = (
        f"服务合同草案\n甲方：{party_a}\n金额：{amount} 元\n"
        f"签署日期：{values.get('sign_date') or ''}\n"
        f"功能清单：{values.get('main_function_list') or ''}\n"
    )
    path.write_text(body, encoding="utf-8")
    return {
        "filename": filename,
        "party_a_name": party_a,
        "total_amount_number": amount,
        "path": str(path),
    }
