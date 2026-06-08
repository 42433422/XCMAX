"""Route PPT generate tasks to compose, enhance, or deterministic recipes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

from modstore_server.ppt_homework_marquee import is_homework_marquee_request

HOMEWORK_RECIPE = "homework_marquee"

COMPOSE_KEYWORDS = re.compile(
    r"生成|制作|创建|写一份|做一份|起草|撰写|ppt|幻灯片|演示|汇报|deck|compose|generate",
    re.I,
)


def resolve_task_route(
    *,
    user_query: str,
    template_path: Optional[Path] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = payload or {}
    q = str(user_query or "").strip()
    has_template = bool(template_path and template_path.is_file())

    if str(payload.get("recipe") or "").strip() == HOMEWORK_RECIPE:
        return {"mode": "enhance", "recipe": HOMEWORK_RECIPE, "use_llm": False}

    if has_template and (
        is_homework_marquee_request(q) or str(payload.get("enhance_homework_marquee") or "") == "1"
    ):
        return {"mode": "enhance", "recipe": HOMEWORK_RECIPE, "use_llm": False}

    if has_template:
        return {"mode": "enhance", "recipe": "", "use_llm": True}

    if COMPOSE_KEYWORDS.search(q) or not q:
        return {"mode": "compose", "recipe": "", "use_llm": True}

    return {"mode": "compose", "recipe": "", "use_llm": True}
