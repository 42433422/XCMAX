"""XCAGI 技术服务合同 · Word 模板 {{field_key}} 填充。"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

_CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "data" / "contracts" / "xcagi_service_v1"
_TEMPLATE_PATH = _CONTRACT_ROOT / "template.docx"
_CONFIG_PATH = _CONTRACT_ROOT / "fill_config.json"
_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "customer_service" / "contracts" / "generated"
)
_OVERRIDES_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "customer_service" / "contracts" / "fields"
)

_PLACEHOLDER_RE = re.compile(r"\{\{([a-z0-9_]+)\}\}")


def contract_assets_dir() -> Path:
    return _CONTRACT_ROOT


def generated_contracts_dir() -> Path:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return _OUTPUT_DIR


def load_fill_config() -> dict[str, Any]:
    if not _CONFIG_PATH.is_file():
        return {"fields": {}, "schema_version": "1.0"}
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def _field_overrides_path(market_user_id: int) -> Path:
    _OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
    return _OVERRIDES_DIR / f"{int(market_user_id)}.json"


def load_field_overrides(market_user_id: int) -> dict[str, str]:
    path = _field_overrides_path(market_user_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(k): str(v) if v is not None else "" for k, v in (data.get("values") or data).items()
        }
    except (OSError, json.JSONDecodeError):
        return {}


def save_field_overrides(
    market_user_id: int, values: dict[str, Any], *, username: str = ""
) -> dict[str, Any]:
    path = _field_overrides_path(market_user_id)
    doc = {
        "market_user_id": int(market_user_id),
        "username": username,
        "values": {str(k): "" if v is None else str(v) for k, v in values.items()},
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def _resolve_field_value(field_def: dict[str, Any], override: str | None) -> str:
    if override is not None and str(override).strip():
        return str(override).strip()
    val = field_def.get("value")
    if val is not None and str(val).strip():
        return str(val).strip()
    default = field_def.get("default")
    if default is not None and str(default).strip():
        return str(default).strip()
    return ""


def _num_to_chinese_upper(num_str: str) -> str:
    try:
        n = float(str(num_str).replace(",", "").strip())
    except ValueError:
        return ""
    if n <= 0:
        return ""
    digits = "零壹贰叁肆伍陆柒捌玖"
    units = ["", "拾", "佰", "仟"]
    big_units = ["", "万", "亿"]
    int_part = int(round(n * 100)) // 100
    dec = int(round(n * 100)) % 100
    jiao, fen = dec // 10, dec % 10

    def four_to_cn(x: int) -> str:
        if x == 0:
            return ""
        s = ""
        zero = False
        for i in range(4):
            d = (x // (10 ** (3 - i))) % 10
            if d == 0:
                if s and not zero:
                    s += "零"
                zero = True
            else:
                s += digits[d] + units[3 - i]
                zero = False
        return s.rstrip("零")

    parts = []
    unit_idx = 0
    while int_part > 0:
        chunk = int_part % 10000
        if chunk:
            chunk_s = four_to_cn(chunk)
            parts.insert(0, chunk_s + big_units[unit_idx])
        elif parts:
            parts.insert(0, "零")
        int_part //= 10000
        unit_idx += 1
    result = "".join(parts) or "零"
    result += "元"
    if jiao == 0 and fen == 0:
        result += "整"
    else:
        if jiao:
            result += digits[jiao] + "角"
        if fen:
            result += digits[fen] + "分"
        elif jiao:
            result += "整"
    return result


def build_merged_fields(
    market_user_id: int,
    *,
    username: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, str]:
    cfg = load_fill_config()
    fields_cfg: dict[str, Any] = cfg.get("fields") or {}
    overrides = load_field_overrides(market_user_id)
    if extra:
        overrides = {**overrides, **{str(k): str(v) for k, v in extra.items() if v is not None}}
    if username and not overrides.get("party_a_name"):
        overrides["party_a_name"] = username
    if not overrides.get("sign_date"):
        overrides["sign_date"] = date.today().isoformat()
    if not overrides.get("contract_number"):
        overrides["contract_number"] = f"XC-{date.today().year}-{int(market_user_id):04d}"

    merged: dict[str, str] = {}
    for key, fdef in fields_cfg.items():
        merged[key] = _resolve_field_value(fdef, overrides.get(key))

    total = merged.get("total_amount_number") or overrides.get("total_amount_number") or ""
    if total and not (merged.get("total_amount_upper") or overrides.get("total_amount_upper")):
        merged["total_amount_upper"] = _num_to_chinese_upper(total)

    for prefix in ("first", "second", "final"):
        num_key = f"{prefix}_payment_amount_number"
        upper_key = f"{prefix}_payment_amount_upper"
        if merged.get(num_key) and not merged.get(upper_key):
            merged[upper_key] = _num_to_chinese_upper(merged[num_key])

    return merged


def list_field_schema() -> dict[str, Any]:
    cfg = load_fill_config()
    fields: dict[str, Any] = cfg.get("fields") or {}
    groups: dict[str, list[dict[str, Any]]] = {}
    for key, fdef in fields.items():
        grp = str(fdef.get("group") or "其它")
        groups.setdefault(grp, []).append(
            {
                "key": key,
                "label": fdef.get("label") or key,
                "type": fdef.get("type") or "string",
                "required": bool(fdef.get("required")),
                "default": fdef.get("default") or "",
                "example": fdef.get("example") or "",
                "note": fdef.get("note") or "",
            }
        )
    return {
        "schema_version": cfg.get("schema_version"),
        "template_file": "template.docx",
        "sample_pdf": "sample_party_b_prefilled.pdf",
        "placeholder_syntax": cfg.get("placeholder_syntax") or "{{field_key}}",
        "groups": groups,
        "party_b_registry_info": cfg.get("party_b_registry_info") or {},
    }


def _render_docx_bytes(template_path: Path, values: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(template_path, "r") as zin:
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.startswith("word/") and item.filename.endswith(".xml"):

                    def repl(m: re.Match[str]) -> str:
                        key = m.group(1)
                        return values.get(key, m.group(0)) if key in values else m.group(0)

                    text = data.decode("utf-8")
                    text = _PLACEHOLDER_RE.sub(repl, text)
                    data = text.encode("utf-8")
                zout.writestr(item, data)
    return buf.getvalue()


def generate_contract_docx(
    market_user_id: int,
    *,
    username: str = "",
    field_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _TEMPLATE_PATH.is_file():
        raise FileNotFoundError(f"合同模板不存在: {_TEMPLATE_PATH}")
    if field_values:
        save_field_overrides(market_user_id, field_values, username=username)
    values = build_merged_fields(market_user_id, username=username, extra=field_values)
    docx_bytes = _render_docx_bytes(_TEMPLATE_PATH, values)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", username or str(market_user_id)).strip(
        "_"
    ) or str(market_user_id)
    cn = values.get("contract_number") or f"XC-{market_user_id}"
    filename = f"{safe_name}_{cn}_技术服务合同.docx".replace("/", "-")
    out_path = _OUTPUT_DIR / filename
    out_path.write_bytes(docx_bytes)

    return {
        "ok": True,
        "market_user_id": int(market_user_id),
        "filename": filename,
        "file_path": str(out_path),
        "contract_number": cn,
        "field_count": len(values),
        "party_a_name": values.get("party_a_name") or "",
    }


def build_contract_wechat_hint(party_a: str, filename: str) -> str:
    return (
        f"{party_a or '客户'}您好，技术服务合同草案已准备好（文件名：{filename}）。"
        "请查收 Word 附件核对甲方信息与金额条款，确认后我们安排签署。"
        "如有修改请在群内说明。"
    )
