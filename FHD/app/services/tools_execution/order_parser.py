from __future__ import annotations

import logging
import re

from app.services.tools_execution.order_parser_helpers import (
    build_missing_prompt,
    cleanup_unit_name,
    normalize_chinese_digits,
    normalize_model_number_token,
    normalize_quantity_token,
    normalize_trailing_unit_name,
    parse_cn_number,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_ORDER_SCHEMA = {
    "type": "object",
    "required": [],
    "properties": {
        "unit_name": {"type": "string"},
        "model_number": {"type": "string"},
        "tin_spec": {"type": "string"},
        "quantity_tins": {"type": "string"},
    },
}


_ORDER_ACTION_PATTERN = r"(?:请|帮我|给我)?\s*(?:打印(?:一下)?|开单|打单|生成)"
_ORDER_PUNCTUATION_PATTERN = r"[，,。；;、：:]"
_ORDER_NUMBER_PATTERN = (
    r"(?:\d+(?:\.\d+)?|[一二两三四五六七八九]?十[一二三四五六七八九]?|[一二两三四五六七八九零〇])"
)
_DOCUMENT_NUMBER_PATTERN = re.compile(
    r"(?P<label>发货单号|送货单号|出货单号|订单号|单号|编号)"
    r"\s*(?:是|为)?\s*[:：]?\s*"
    r"(?P<number>[0-9A-Za-z][0-9A-Za-z_-]{0,63})"
)


def _clean_named_product(value: str) -> str:
    """Return a literal product-name slot without treating it as a model number.

    Natural-language delivery requests often name a product instead of providing its
    internal model.  This helper deliberately keeps that name intact: the caller
    must later resolve it against the selected customer's tenant-local product
    catalogue instead of guessing from an arbitrary fuzzy match.
    """

    name = str(value or "").strip(" ，,。；;、：:\t\n")
    name = re.sub(r"^(?:产品(?:名称)?|品名)\s*(?:是|为)?\s*", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def parse_named_product_order(order_text: str) -> dict | None:
    """Parse a complete delivery request expressed as customer + product name.

    Examples:
    - ``打印金汉武发货单，黑棕面用修色精，规格28，3桶``
    - ``开单 金汉武，黑棕面用修色精，规格28，3桶``

    This recognises only explicit, complete name-based requests.  It returns
    ``None`` for model-number requests so the existing strict model parser keeps
    ownership of those inputs.
    """

    source = str(order_text or "").strip()
    if not source:
        return None

    unit_name = ""
    product_and_measurements = ""
    recipient_action_match = re.match(
        rf"^\s*给\s*(?P<unit>.+?)\s*"
        rf"(?:打单|开单|生成(?:发货单|送货单|出货单)?|打印(?:一下)?(?:发货单|送货单|出货单)?)"
        rf"\s*{_ORDER_PUNCTUATION_PATTERN}+\s*(?P<tail>.+)$",
        source,
    )
    if recipient_action_match:
        unit_name = cleanup_unit_name(recipient_action_match.group("unit"))
        product_and_measurements = recipient_action_match.group("tail")
    else:
        action_match = re.match(rf"^\s*{_ORDER_ACTION_PATTERN}\s*", source)
        if not action_match:
            return None

        remainder = source[action_match.end() :].strip()
        if not remainder:
            return None

        delivery_match = re.match(
            rf"^(?P<unit>.+?)\s*(?:的)?\s*(?:发货单|送货单|出货单)\s*{_ORDER_PUNCTUATION_PATTERN}+\s*(?P<tail>.+)$",
            remainder,
        )
        if delivery_match:
            unit_name = cleanup_unit_name(delivery_match.group("unit"))
            product_and_measurements = delivery_match.group("tail")
        else:
            # “开单 客户，产品名，规格…”，有明确分隔符才进入名字模式，避免
            # 把无分隔的历史编号语句误切成客户/产品。
            simple_match = re.match(
                rf"^(?P<unit>[^\s，,。；;、：:]+)\s*{_ORDER_PUNCTUATION_PATTERN}+\s*(?P<tail>.+)$",
                remainder,
            )
            if simple_match:
                unit_name = cleanup_unit_name(simple_match.group("unit"))
                product_and_measurements = simple_match.group("tail")

    if not unit_name or not product_and_measurements:
        return None

    # In a literal-product request, an explicitly labelled number is a document
    # number rather than product identity.  This is intentionally scoped to
    # this parser: bare ``编号9803`` model-number orders still take the strict
    # model path below.  ``型号`` remains a product identifier in every form.
    document_number = ""
    document_number_label = ""
    number_match = _DOCUMENT_NUMBER_PATTERN.search(product_and_measurements)
    if number_match:
        document_number = str(number_match.group("number") or "").strip()
        document_number_label = str(number_match.group("label") or "").strip()
        product_and_measurements = (
            product_and_measurements[: number_match.start()]
            + " "
            + product_and_measurements[number_match.end() :]
        ).strip()

    # Explicit model labels always remain in the strict model-number flow.
    if re.search(r"(?:型号)\s*[:：]?", product_and_measurements):
        return None

    spec_match = re.search(
        rf"(?:的)?规格\s*[:：]?\s*(?P<spec>{_ORDER_NUMBER_PATTERN})",
        product_and_measurements,
    )
    if not spec_match:
        return None
    spec_value = parse_cn_number(spec_match.group("spec"))
    if spec_value is None or float(spec_value) <= 0:
        return None

    quantity_match = re.search(
        rf"(?:一共|总共|共|要|来|拿)?\s*(?P<quantity>{_ORDER_NUMBER_PATTERN})\s*桶",
        product_and_measurements,
    )
    if not quantity_match:
        return None
    quantity_value = parse_cn_number(quantity_match.group("quantity"))
    if quantity_value is None or float(quantity_value) <= 0:
        return None

    unit_price = None
    price_match = re.search(
        rf"(?:单价|价格)\s*(?:是|为)?\s*[:：]?\s*(?P<price>{_ORDER_NUMBER_PATTERN})\s*元?",
        product_and_measurements,
    )
    if price_match:
        unit_price = parse_cn_number(price_match.group("price"))
        if unit_price is None or float(unit_price) < 0:
            return None

    first_measurement = min(
        match.start() for match in (spec_match, quantity_match, price_match) if match is not None
    )
    product_name = _clean_named_product(product_and_measurements[:first_measurement])
    if not product_name or re.match(r"^(?:编号|型号)\b", product_name):
        return None
    # A bare ASCII token is much more likely to be an omitted-label model number.
    if re.fullmatch(r"[0-9A-Za-z-]{3,16}", product_name):
        return None

    product = {
        "name": product_name,
        "quantity_tins": int(quantity_value),
        "tin_spec": float(spec_value),
    }
    if unit_price is not None:
        product["unit_price"] = float(unit_price)

    result = {
        "success": True,
        "unit_name": unit_name,
        "products": [product],
    }
    if document_number:
        result["order_number"] = document_number
        result["order_number_provenance"] = {
            "kind": "explicit_document_number",
            "label": document_number_label,
            "value": document_number,
        }
    return result


from app.services.tools_execution.order_text_parser import (
    _parse_order_text,
)
