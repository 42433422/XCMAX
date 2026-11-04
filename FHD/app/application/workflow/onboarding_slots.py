"""Linear extraction of the two explicitly quoted onboarding records."""

from __future__ import annotations


def _first_onboarding_quoted_slot(text: str, prefixes: tuple[str, ...]) -> str | None:
    """Walk forward once, preserving the original first nonempty quoted match."""
    cursor = 0
    length = len(text)
    while cursor < length:
        prefix = next((value for value in prefixes if text.startswith(value, cursor)), None)
        if prefix is None:
            cursor += 1
            continue
        cursor += len(prefix)
        while cursor < length and text[cursor].isspace():
            cursor += 1
        if cursor == length or text[cursor] not in ("「", "“", '"', "'"):
            continue
        cursor += 1
        start = cursor
        # Any of these closing quotes ended the old match, including mixed styles.
        while cursor < length and text[cursor] not in ("」", "”", '"', "'"):
            cursor += 1
        if cursor == length:
            # No later candidate can close either; never restart over this suffix.
            return None
        if cursor > start:
            return text[start:cursor].strip()
        cursor += 1
    return None


def _onboarding_first_order_slots(message: str) -> tuple[str, str] | None:
    """Extract the two seeded records from the deterministic onboarding prompt."""
    text = str(message or "")
    if "新手第一单" not in text or "演示出货单" not in text:
        return None
    customer = _first_onboarding_quoted_slot(text, ("查询客户",))
    product = _first_onboarding_quoted_slot(text, ("查询商品", "查询产品"))
    return (customer, product) if customer and product else None
