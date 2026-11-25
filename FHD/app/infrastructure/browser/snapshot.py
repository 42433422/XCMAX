"""Mask editable values in Playwright snapshots without changing the page.

This is fixed, read-only inspection code. Browser plans never provide JavaScript.
Arbitrary page text is still untrusted and may contain other sensitive information.
"""

from __future__ import annotations

import re
from typing import Any

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

_MAX_RAW_CHARS = 120_000
_MAX_VALUE_CHARS = 131_072
_MAX_VALUES = 2_000
EDITABLE_SELECTOR = "input, select, textarea, [contenteditable]"
SCREENSHOT_MASK_SELECTOR = EDITABLE_SELECTOR + ", iframe, frame, object, embed"
_EDITABLE_ROLE = re.compile(r"^(?:textbox|searchbox|combobox|spinbutton|slider)(?:\s|$)")
_ROLE_PREFIX = re.compile(r"^[a-z][a-z0-9]*(?=\s|$)")
_FORM_VALUES = """elements => {
    if (elements.length > 500) throw new Error('snapshot_privacy_limit');
    const values = new Set();
    let size = 0, nodes = 0;
    const add = value => {
        if (typeof value !== 'string' || !value.trim() || values.has(value)) return;
        size += value.length;
        if (value.length > 16384 || size > 131072 || values.size >= 2000)
            throw new Error('snapshot_privacy_limit');
        values.add(value);
    };
    for (const element of elements) {
        if (element.tagName === 'TEXTAREA' || (element.tagName === 'INPUT' &&
            !['checkbox','radio','file','submit','reset','button','image'].includes(element.type)))
            add(element.value);
        if (element.tagName === 'SELECT') {
            for (const option of element.selectedOptions) {
                add(option.value); add(option.textContent);
            }
        }
        if (element.isContentEditable) {
            add(element.textContent);
            const walker = element.ownerDocument.createTreeWalker(element, 4);
            while (walker.nextNode()) {
                if (++nodes > 2000) throw new Error('snapshot_privacy_limit');
                add(walker.currentNode.textContent);
            }
        }
    }
    return [...values];
}"""


def redact_snapshot(snapshot: str, values: list[str]) -> str:
    """Parse YAML without constructing page-supplied objects, then mask values.

    Editable-role children are removed even if a field changes during inspection.
    Scalar-node values preserve strings such as 00123 without YAML type coercion.
    """
    if (
        len(snapshot) > _MAX_RAW_CHARS
        or len(values) > _MAX_VALUES
        or any(not isinstance(value, str) for value in values)
        or sum(len(value) for value in values) > _MAX_VALUE_CHARS
    ):
        raise ValueError("browser_snapshot_privacy_limit")
    secrets = {
        variant
        for value in values
        for variant in (
            value,
            re.sub(r"\s+", " ", value.replace("\u200b", "").replace("\u00ad", "")).strip(),
        )
        if variant
    }
    pattern = (
        re.compile("|".join(re.escape(value) for value in sorted(secrets, key=len, reverse=True)))
        if secrets
        else None
    )

    def text(value: str, *, role: bool = False) -> str:
        prefix = _ROLE_PREFIX.match(value) if role else None
        offset = prefix.end() if prefix else 0
        return value[:offset] + (
            pattern.sub("[redacted]", value[offset:]) if pattern else value[offset:]
        )

    visited = 0

    def scrub(node: Any, depth: int = 0, *, role: bool = False) -> Any:
        nonlocal visited
        visited += 1
        if visited > 5_000 or depth > 50:
            raise ValueError("browser_snapshot_privacy_limit")
        if isinstance(node, ScalarNode):
            return text(node.value, role=role)
        if isinstance(node, SequenceNode):
            return [scrub(child, depth + 1, role=True) for child in node.value]
        if isinstance(node, MappingNode):
            result = {}
            for key, child in node.value:
                if not isinstance(key, ScalarNode):
                    raise ValueError("browser_snapshot_privacy_invalid")
                label = text(key.value, role=True)
                if label in result:
                    raise ValueError("browser_snapshot_privacy_invalid")
                result[label] = (
                    "[redacted]" if _EDITABLE_ROLE.match(key.value) else scrub(child, depth + 1)
                )
            return result
        raise ValueError("browser_snapshot_privacy_invalid")

    try:
        tree = yaml.compose(snapshot, Loader=yaml.SafeLoader)
        return (
            yaml.safe_dump(scrub(tree), allow_unicode=True, sort_keys=False).strip() if tree else ""
        )
    except yaml.YAMLError:
        raise ValueError("browser_snapshot_privacy_invalid") from None


def _frames(page: Any) -> list[Any]:
    frames = page.frames
    if not isinstance(frames, list) or len(frames) > 16:
        raise ValueError("browser_snapshot_privacy_limit")
    return frames


def _collect_values(values: set[str], found: Any) -> None:
    if not isinstance(found, list) or any(not isinstance(value, str) for value in found):
        raise ValueError("browser_snapshot_privacy_invalid")
    values.update(found)
    if len(values) > _MAX_VALUES or sum(len(value) for value in values) > _MAX_VALUE_CHARS:
        raise ValueError("browser_snapshot_privacy_limit")


def redacted_page_snapshot_sync(page: Any, *, timeout: float) -> str:
    """Use the same privacy boundary for the desktop's synchronous adapter."""
    values: set[str] = set()

    def collect() -> None:
        for frame in _frames(page):
            _collect_values(values, frame.locator(EDITABLE_SELECTOR).evaluate_all(_FORM_VALUES))

    collect()
    snapshot = page.locator("body").aria_snapshot(timeout=timeout)
    collect()
    return redact_snapshot(snapshot, list(values))


async def redacted_page_snapshot(page: Any, *, timeout: float) -> str:
    """Inspect around capture; fail closed if any frame/value inspection fails."""
    values: set[str] = set()

    async def collect() -> None:
        for frame in _frames(page):
            _collect_values(
                values, await frame.locator(EDITABLE_SELECTOR).evaluate_all(_FORM_VALUES)
            )

    await collect()
    snapshot = await page.locator("body").aria_snapshot(timeout=timeout)
    await collect()
    return redact_snapshot(snapshot, list(values))
