"""Repository skills in the OpenHands ``SKILL.md`` format.

A skill is a folder under ``.agents/skills/<name>/SKILL.md`` with YAML
front-matter (``name``, ``description``, optional ``triggers``) and Markdown
instructions. Only skills whose triggers appear in the current message are
injected into the planner rules, so unrelated guidance cannot leak into a turn.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

__all__ = ["Skill", "load_skills", "match_skills", "skill_rules"]

_SKILL_GLOB = "*/SKILL.md"
_MAX_SKILL_CHARS = 1500


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    triggers: tuple[str, ...]
    content: str


def _workspace_roots() -> list[Path]:
    roots: list[Path] = []
    configured = str(os.environ.get("XCAGI_SKILLS_DIRS") or "").strip()
    if configured:
        roots.extend(Path(item).expanduser() for item in configured.split(os.pathsep) if item)
    repo_root = Path(__file__).resolve().parents[4]
    roots.extend([repo_root / ".agents" / "skills", repo_root / ".openhands" / "skills"])
    return roots


def _parse_skill(path: Path) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    body = text
    meta: dict[str, Any] = {}
    if text.startswith("---"):
        _, _, rest = text.partition("---")
        front, _, body = rest.partition("\n---")
        try:
            parsed = yaml.safe_load(front)
        except yaml.YAMLError:
            return None
        meta = parsed if isinstance(parsed, dict) else {}
    name = str(meta.get("name") or path.parent.name).strip()
    description = str(meta.get("description") or "").strip()
    raw_triggers = meta.get("triggers") or meta.get("when") or []
    if isinstance(raw_triggers, str):
        raw_triggers = [raw_triggers]
    triggers = tuple(
        str(item).strip().casefold()
        for item in raw_triggers
        if isinstance(item, (str, int, float)) and str(item).strip()
    )
    content = body.strip()
    if not name or not content:
        return None
    return Skill(name=name, description=description, triggers=triggers, content=content)


def load_skills(roots: list[Path] | None = None) -> list[Skill]:
    skills: list[Skill] = []
    seen: set[str] = set()
    for root in roots if roots is not None else _workspace_roots():
        if not root.is_dir():
            continue
        for path in sorted(root.glob(_SKILL_GLOB)):
            skill = _parse_skill(path)
            if skill is None or skill.name in seen:
                continue
            seen.add(skill.name)
            skills.append(skill)
    return skills


def match_skills(message: str, skills: list[Skill] | None = None) -> list[Skill]:
    """Return skills whose triggers appear in the message (case-insensitive)."""
    text = str(message or "").casefold()
    if not text:
        return []
    return [skill for skill in (skills or load_skills()) if any(t in text for t in skill.triggers)]


def skill_rules(message: str, skills: list[Skill] | None = None) -> list[str]:
    """Planner rule lines for matched skills, bounded per skill."""
    rules: list[str] = []
    for skill in match_skills(message, skills):
        body = skill.content[:_MAX_SKILL_CHARS]
        rules.append(f"技能「{skill.name}」：{body}")
    return rules
