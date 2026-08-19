"""Deterministic customer-name extraction helpers for intent slots."""

from __future__ import annotations

import re


def extract_multi_unit_names(message: str) -> list[str]:
    """Extract one or more customer names from a shipment phrase."""
    clean_message = message
    for prefix in ("发货单", "送货单", "出货单", "开单", "生成"):
        if clean_message.startswith(prefix):
            clean_message = clean_message[len(prefix) :].strip()

    quantity_pattern = r"\d+[桶箱件个]|[一二三四五六七八九十零〇]+[桶箱件个]"
    separators = ["和", "、", ",", "，"]
    if any(separator in clean_message for separator in separators):
        parts = re.split("|".join(re.escape(value) for value in separators), clean_message)
        names = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            name = extract_name_before_quantity(part, quantity_pattern)
            if name:
                names.append(name)
        if names:
            return names

    name = extract_name_before_quantity(clean_message, quantity_pattern)
    return [name] if name else []


def extract_name_before_quantity(text: str, quantity_pattern: str) -> str | None:
    """Extract a 2-10 character customer name before a quantity token."""
    quantity = re.search(quantity_pattern, text)
    name_part = text[: quantity.start()] if quantity else text
    name_part = name_part.strip().rstrip("和的")
    match = re.match(r"^([^\s\d]{2,10})", name_part)
    if match:
        return match.group(1)
    if 2 <= len(name_part) <= 10:
        return name_part
    return None
