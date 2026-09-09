"""Standalone salutations must not consume a following business instruction."""

import re

GREETING_PATTERN = (
    r"^\s*(?:你好|您好|嗨|(?:hi|hello)(?:\s+there)?|早上好|下午好|晚上好|"
    r"在吗|有人吗|在不在|哈喽|嘿)(?:[啊呀])?[\s!！。.?？]*$"
)
_GREETING = re.compile(GREETING_PATTERN, re.IGNORECASE)


def is_standalone_greeting(message: str) -> bool:
    return bool(_GREETING.fullmatch(message or ""))


_FAREWELL = re.compile(
    r"^\s*(?:再见|拜拜|拜了|先这样|(?:good\s*)?bye|see\s+you)"
    r"(?:[啦了啊呀吧])?[\s!！。.?？]*$",
    re.IGNORECASE,
)


def is_standalone_goodbye(message: str) -> bool:
    """A farewell cannot stand in for cancelling an operation or quoted content."""
    return bool(_FAREWELL.fullmatch(message or ""))
