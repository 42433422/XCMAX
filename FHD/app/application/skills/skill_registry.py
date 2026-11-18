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
_MAX_RULE_CHARS = 6000
_MAX_FILE_BYTES = 64 * 1024
_MAX_LOADED_SKILLS = 64
_MAX_MATCHED_SKILLS = 4
_MAX_NAME_CHARS = 80


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
        with path.open("rb") as stream:
            raw = stream.read(_MAX_FILE_BYTES + 1)
        if len(raw) > _MAX_FILE_BYTES:
            return None
        text = raw.decode("utf-8")
    except (OSError, UnicodeError):
        return None
    body = text
    meta: dict[str, Any] = {}
    if text.startswith("---"):
        _, _, rest = text.partition("---")
        front, separator, body = rest.partition("\n---")
        if not separator:
            return None
        try:
            parsed = yaml.safe_load(front)
        except (yaml.YAMLError, RecursionError):
            return None
        meta = parsed if isinstance(parsed, dict) else {}
    name = meta.get("name") or path.parent.name
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= _MAX_NAME_CHARS:
        return None
    name = name.strip()
    description = meta.get("description") or ""
    if not isinstance(description, str):
        return None
    description = description.strip()[:300]
    raw_triggers = meta.get("triggers") or meta.get("when") or []
    if isinstance(raw_triggers, str):
        raw_triggers = [raw_triggers]
    if not isinstance(raw_triggers, list):
        return None
    triggers = tuple(
        item.strip().casefold()
        for item in raw_triggers[:32]
        if isinstance(item, str) and 1 <= len(item.strip()) <= 120
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
            if len(skills) >= _MAX_LOADED_SKILLS:
                return skills
            try:
                path.resolve().relative_to(root.resolve())
            except (OSError, RuntimeError, ValueError):
                continue
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
    available = load_skills() if skills is None else skills
    return [skill for skill in available if any(t in text for t in skill.triggers)]


def skill_rules(message: str, skills: list[Skill] | None = None) -> list[str]:
    """Planner rule lines for matched skills, bounded per skill."""
    if os.environ.get("XCAGI_AGENT_SKILLS_ENABLED", "1") == "0":
        return []
    rules: list[str] = []
    remaining = _MAX_RULE_CHARS
    for skill in match_skills(message, skills)[:_MAX_MATCHED_SKILLS]:
        body = skill.content[:_MAX_SKILL_CHARS]
        rule = f"技能「{skill.name[:_MAX_NAME_CHARS]}」：{body}"[:remaining]
        if not rule:
            break
        rules.append(rule)
        remaining -= len(rule)
    return rules
