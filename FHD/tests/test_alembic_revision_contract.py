from __future__ import annotations

import ast
from pathlib import Path


def test_alembic_revision_ids_fit_default_version_table() -> None:
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    failures: list[str] = []
    for path in sorted(versions.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = ""
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(
                isinstance(target, ast.Name) and target.id == "revision" for target in targets
            ):
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                revision = value.value
                break
        if not revision:
            failures.append(f"{path.name}: missing literal revision")
        elif len(revision) > 32:
            failures.append(f"{path.name}: {revision!r} is {len(revision)} chars")

    assert not failures, "Alembic default version_num is VARCHAR(32):\n" + "\n".join(failures)
