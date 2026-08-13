"""Versioned, server-owned course catalog for real business practice."""

from __future__ import annotations

from typing import Any

from .builders import COURSE_VERSION
from .course_definitions import COURSES

COURSE_BY_ID = {str(course["id"]): course for course in COURSES}


def public_course(course: dict[str, Any]) -> dict[str, Any]:
    """Strip server-only verifier keys before returning the public DTO."""
    result = {key: value for key, value in course.items() if key != "steps"}
    result["steps"] = [
        {key: value for key, value in step.items() if key != "verifier"} for step in course["steps"]
    ]
    return result


__all__ = ["COURSE_BY_ID", "COURSES", "COURSE_VERSION", "public_course"]
