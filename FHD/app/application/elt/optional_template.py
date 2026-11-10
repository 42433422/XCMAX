"""Optional template selection shared by capsule templates and worksheet templates.

Archive capsules start with nothing selected (index -1). Opening the picker
does not apply a template. An explicit in-range index applies one; a busy
picker, a bool, or an out-of-range index is ignored. No template is valid.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def initial_optional_template_index(*, optional: bool) -> int:
    return -1 if optional else 0


def choose_optional_template(templates: list[T], index: int, *, busy: bool = False) -> T | None:
    if busy or isinstance(index, bool) or not isinstance(index, int):
        return None
    if index < 0 or index >= len(templates):
        return None
    return templates[index]
