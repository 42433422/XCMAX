"""Migrate Trae memory to Persy Unified Memory Graph.

读取 ~/.trae-cn/memory/ 下的 project_memory.md 和 user_profile.md，
解析为 constraint/convention/lesson/preference 节点写入 Persy。

用法:
    python scripts/dev/migrate_trae_memory_to_persy.py \
        --memory-root ~/.trae-cn/memory/projects/<project-dir>/ \
        --persy-api http://localhost:8000/api/knowledge/v2 \
        --scope project --scope-id XCMAX \
        --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.db.models.memory_graph import MemoryNodeType

_SECTION_PATTERN = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


class TraeMemoryMigrator:
    """Trae memory → Persy 迁移器。"""

    def __init__(self, memory_root: Path, scope: str, scope_id: str) -> None:
        self._root = Path(memory_root)
        self._scope = scope
        self._scope_id = scope_id

    def parse_project_memory(self) -> dict[str, list[str]]:
        """解析 project_memory.md，返回 {section_title: [items]}。"""
        project_memory = self._find_project_memory()
        if project_memory is None:
            return {}
        text = project_memory.read_text(encoding="utf-8")
        sections: dict[str, list[str]] = {}
        current_section: str | None = None
        for line in text.splitlines():
            line = line.rstrip()
            if line.startswith("## "):
                current_section = line[3:].strip()
                sections[current_section] = []
            elif current_section and line.startswith("- "):
                item = line[2:].strip()
                if item:
                    sections[current_section].append(item)
        return sections

    def migrate(self, app_service: MemoryGraphAppService, dry_run: bool = False) -> dict[str, int]:
        sections = self.parse_project_memory()
        type_mapping = {
            "Hard Constraints": MemoryNodeType.CONSTRAINT,
            "Engineering Conventions": MemoryNodeType.CONVENTION,
            "Lessons Learned": MemoryNodeType.LESSON,
        }
        counts: dict[str, int] = {"constraint": 0, "convention": 0, "lesson": 0}
        for section_title, items in sections.items():
            node_type = type_mapping.get(section_title)
            if node_type is None:
                continue
            type_key = node_type.value
            for item in items:
                title, _, content = item.partition("：")
                if not content:
                    title, _, content = item.partition(":")
                if not content:
                    title = item[:80]
                    content = item
                if dry_run:
                    counts[type_key] += 1
                    continue
                result = app_service.ingest_engineering(
                    type=node_type,
                    title=title.strip()[:160],
                    content=content.strip(),
                    scope=self._scope,
                    scope_id=self._scope_id,
                    tags=["trae-memory-migrated"],
                )
                if result.get("success"):
                    counts[type_key] += 1
        return counts

    def _find_project_memory(self) -> Path | None:
        candidates = [
            self._root / "project_memory.md",
            self._root / "projects" / "project_memory.md",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        for project_dir in (
            (self._root / "projects").iterdir() if (self._root / "projects").exists() else []
        ):
            pm = project_dir / "project_memory.md"
            if pm.exists():
                return pm
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Trae memory to Persy")
    parser.add_argument("--memory-root", required=True, help="Trae memory root path")
    parser.add_argument("--persy-api", default="http://localhost:8000/api/knowledge/v2")
    parser.add_argument("--scope", default="project")
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    migrator = TraeMemoryMigrator(
        memory_root=Path(args.memory_root).expanduser(),
        scope=args.scope,
        scope_id=args.scope_id,
    )
    sections = migrator.parse_project_memory()
    print(f"[migrate] 解析到 sections: {list(sections.keys())}")
    for section, items in sections.items():
        print(f"  {section}: {len(items)} items")

    if args.dry_run:
        print("[migrate] dry-run 模式，不实际写入")
        return 0

    print("[migrate] 注意：需在 Persy 服务运行时通过 HTTP API 迁移")
    print("[migrate] 或在 Python 进程内直接调用 app_service")
    return 0


if __name__ == "__main__":
    sys.exit(main())
