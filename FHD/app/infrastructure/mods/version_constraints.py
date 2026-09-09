"""Numeric Mod versions, including four-part releases; unknown syntax never matches."""

import re
from itertools import zip_longest


def version_parts(value: str) -> tuple[int, ...]:
    if (
        not isinstance(value, str)
        or len(value) > 100
        or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,7}", value)
    ):
        raise ValueError("Invalid numeric Mod version")
    return tuple(int(part) for part in value.split("."))


def compare_versions(left: str, right: str) -> int:
    for a, b in zip_longest(version_parts(left), version_parts(right), fillvalue=0):
        if a != b:
            return 1 if a > b else -1
    return 0


def _clause(version: str, clause: str) -> bool:
    if clause == "*":
        return True
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*\.[xX*]", clause):
        prefix = version_parts(clause[:-2])
        actual = version_parts(version)
        return tuple((actual + (0,) * len(prefix))[: len(prefix)]) == prefix
    match = re.fullmatch(r"(>=|<=|==|!=|>|<|=|\^|~)?([0-9]+(?:\.[0-9]+){0,7})", clause)
    if not match:
        raise ValueError("Unsupported Mod version constraint")
    operator, required = match.groups()
    order = compare_versions(version, required)
    if operator in {"^", "~"}:
        parts = list(version_parts(required))
        index = (
            min(1, len(parts) - 1)
            if operator == "~"
            else next((i for i, value in enumerate(parts) if value), len(parts) - 1)
        )
        upper = parts[:index] + [parts[index] + 1]
        return order >= 0 and compare_versions(version, ".".join(map(str, upper))) < 0
    return {
        None: order == 0,
        "=": order == 0,
        "==": order == 0,
        "!=": order != 0,
        ">=": order >= 0,
        "<=": order <= 0,
        ">": order > 0,
        "<": order < 0,
    }[operator]


def version_satisfies(version: str, specification: str) -> bool:
    try:
        version_parts(version)
        if not isinstance(specification, str) or len(specification) > 256:
            return False
        if not specification.strip():
            return True
        normalized = re.sub(r"([<>=!~^]+)\s+", r"\1", specification.strip())
        clauses = re.split(r"\s*,\s*|\s+", normalized)
        if len(clauses) > 16:
            return False
        return all(_clause(version, clause) for clause in clauses)
    except (ValueError, TypeError):
        return False
