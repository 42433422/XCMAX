#!/usr/bin/env python
"""Sync the standalone vibe_coding package from the upstream eskill prototype.

Usage::

    python scripts/sync_from_eskill.py [--check] [--source ../eskill-prototype]

Behaviour:

- ``runtime/``       <- eskill.code (validator, sandbox, diagnostics, patch
                       generator, runtime, store, hybrid). Imports that point
                       at ``eskill.models`` / ``eskill.static_executor`` /
                       ``eskill.code.models`` are rewritten to the local
                       ``vibe_coding._internals`` and ``vibe_coding.runtime``
                       counterparts.
- ``nl/``            <- eskill.vibe_coding.nl (verbatim).
- ``code_factory.py``,
  ``workflow_models.py``,
  ``workflow_factory.py`` <- eskill.vibe_coding.* with ``..code`` rewritten.
- ``workflow_engine.py`` <- code-layer-only adaptation (the standalone version
                       drops the ``ESkillRuntime`` / ``ESkillNodeWrapper`` wiring;
                       the script edits the file accordingly).
- ``audit.py``,
  ``facade.py``,
  ``cli.py``         <- code-layer-only adaptations.

Pass ``--check`` to diff without writing.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT.parent / "eskill-prototype"

# (source path relative to source/src/eskill, dest relative to dest/src/vibe_coding,
# replacement function or None for verbatim)


@dataclass(slots=True)
class FileTask:
    src: str
    dst: str
    rewrite: str  # name of rewrite function in this file


# ----------------------------------------------------------------- rewrite helpers


def _rewrite_runtime(src: str) -> str:
    """Rewrite eskill.code.* sources to live under vibe_coding.runtime / _internals."""
    out = src
    out = re.sub(
        r"from \.\.models import (.+)",
        lambda m: _split_import(m.group(1)),
        out,
    )
    out = out.replace(
        "from .. import static_executor",
        "from .._internals import quality as static_executor",
    )
    out = out.replace(
        "from ..static_executor import",
        "from .._internals.quality import",
    )
    # eskill.code.models is now vibe_coding._internals.code_models
    out = out.replace(
        "from .models import",
        "from .._internals.code_models import",
    )
    # cross-references inside eskill.code (e.g. hybrid imports runtime / store / ESkill)
    out = re.sub(
        r"from \.\.runtime import (.+)",
        r"# removed: ESkillRuntime not part of standalone vibe_coding\n# from ..runtime import \1",
        out,
    )
    return out


def _split_import(symbols: str) -> str:
    """Map a comma-separated `from ..models import ...` symbol list onto _internals."""
    items = [s.strip() for s in symbols.split(",") if s.strip()]
    keep = [s for s in items if s in {"TriggerPolicy", "EvolutionEvent", "now_iso"}]
    if not keep:
        return f"# unmapped models import: {symbols}"
    return "from .._internals import " + ", ".join(keep)


def _rewrite_nl(src: str) -> str:
    return src  # verbatim


def _rewrite_workflow_models(src: str) -> str:
    return src  # verbatim


def _rewrite_code_factory(src: str) -> str:
    out = src
    out = out.replace(
        "from ..code import (\n    CodeFunctionSignature,\n    CodeSandbox,\n    CodeSkill,\n    CodeSkillVersion,\n    CodeTestCase,\n    CodeValidator,\n    JsonCodeSkillStore,\n)",
        (
            "from ._internals import CodeFunctionSignature, CodeSkill, CodeSkillVersion, CodeTestCase\n"
            "from .runtime import CodeSandbox, CodeValidator, JsonCodeSkillStore"
        ),
    )
    out = out.replace(
        "from ..code.validator import ALLOWED_IMPORT_MODULES",
        "from .runtime.validator import ALLOWED_IMPORT_MODULES",
    )
    out = out.replace(
        "from ..models import TriggerPolicy",
        "from ._internals import TriggerPolicy",
    )
    out = out.replace(
        "from .nl.llm import LLMClient",
        "from .nl.llm import LLMClient",
    )
    return out


def _rewrite_workflow_factory(src: str) -> str:
    out = src
    out = out.replace(
        "from .config_factory import NLConfigSkillFactory",
        "# removed: config-layer factory unavailable in standalone\n# from .config_factory import NLConfigSkillFactory",
    )
    out = out.replace(
        "    config_factory: NLConfigSkillFactory | None = None,",
        "    config_factory: object | None = None,",
    )
    return out


def _rewrite_workflow_engine(src: str) -> str:
    out = src
    out = out.replace(
        "from ..code import CodeSkillRuntime",
        "from .runtime import CodeSkillRuntime",
    )
    out = out.replace(
        "from ..models import TriggerPolicy",
        "from ._internals import TriggerPolicy",
    )
    # Standalone has no ESkillRuntime / ESkillNodeWrapper / JsonSkillStore
    out = out.replace(
        "from ..runtime import ESkillRuntime",
        "ESkillRuntime = None  # unavailable in standalone vibe_coding",
    )
    out = out.replace(
        "from ..skill_node_layer import ESkillNodeWrapper, SkillNodeConfig",
        "ESkillNodeWrapper = None  # unavailable in standalone vibe_coding\nSkillNodeConfig = None  # unavailable in standalone vibe_coding",
    )
    out = out.replace(
        "from ..store import JsonSkillStore",
        "JsonSkillStore = None  # unavailable in standalone vibe_coding",
    )
    return out


def _rewrite_audit(src: str) -> str:
    out = src
    out = out.replace(
        "from ..code import CodeSkill, JsonCodeSkillStore",
        "from ._internals import CodeSkill\nfrom .runtime import JsonCodeSkillStore",
    )
    out = out.replace(
        "from ..models import ESkill",
        "ESkill = object  # unavailable in standalone vibe_coding",
    )
    out = out.replace(
        "from ..store import JsonSkillStore",
        "JsonSkillStore = None  # unavailable in standalone vibe_coding",
    )
    return out


def _rewrite_facade(src: str) -> str:
    out = src
    out = out.replace(
        "from ..code import (\n    CodeSkill,\n    CodeSkillRun,\n    CodeSkillRuntime,\n    JsonCodeSkillStore,\n    OpenAICodePatchGenerator,\n    RuleBasedCodePatchGenerator,\n)",
        (
            "from ._internals import CodeSkill, CodeSkillRun\n"
            "from .runtime import (\n"
            "    CodeSkillRuntime,\n"
            "    JsonCodeSkillStore,\n"
            "    OpenAICodePatchGenerator,\n"
            "    RuleBasedCodePatchGenerator,\n"
            ")"
        ),
    )
    out = out.replace(
        "from ..models import ESkill",
        "ESkill = object  # unavailable in standalone vibe_coding",
    )
    out = out.replace(
        "from ..runtime import ESkillRuntime",
        "ESkillRuntime = None  # unavailable in standalone vibe_coding",
    )
    out = out.replace(
        "from ..store import JsonSkillStore",
        "JsonSkillStore = None  # unavailable in standalone vibe_coding",
    )
    out = out.replace(
        "from .config_factory import NLConfigSkillFactory",
        "NLConfigSkillFactory = None  # not available in standalone code-layer build",
    )
    return out


def _rewrite_cli(src: str) -> str:
    return src  # verbatim — CLI is logic-only, no eskill imports


def _rewrite_init(src: str) -> str:
    out = src
    out = out.replace(
        "from .code_factory import NLCodeSkillFactory, VibeCodingError",
        "from .code_factory import NLCodeSkillFactory, VibeCodingError",
    )
    out = out.replace(
        "from .config_factory import NLConfigSkillFactory",
        "NLConfigSkillFactory = None  # standalone is code-layer only",
    )
    return out


REWRITERS = {
    "runtime": _rewrite_runtime,
    "nl": _rewrite_nl,
    "workflow_models": _rewrite_workflow_models,
    "workflow_engine": _rewrite_workflow_engine,
    "workflow_factory": _rewrite_workflow_factory,
    "code_factory": _rewrite_code_factory,
    "audit": _rewrite_audit,
    "facade": _rewrite_facade,
    "cli": _rewrite_cli,
    "init": _rewrite_init,
}


# ----------------------------------------------------------------- task list

TASKS = [
    # runtime/ from eskill.code/
    FileTask("src/eskill/code/__init__.py", "src/vibe_coding/runtime/__init__.py", "runtime"),
    FileTask("src/eskill/code/validator.py", "src/vibe_coding/runtime/validator.py", "runtime"),
    FileTask("src/eskill/code/sandbox.py", "src/vibe_coding/runtime/sandbox.py", "runtime"),
    FileTask("src/eskill/code/diagnostics.py", "src/vibe_coding/runtime/diagnostics.py", "runtime"),
    FileTask("src/eskill/code/patch_generator.py", "src/vibe_coding/runtime/patch_generator.py", "runtime"),
    FileTask("src/eskill/code/runtime.py", "src/vibe_coding/runtime/runtime.py", "runtime"),
    FileTask("src/eskill/code/store.py", "src/vibe_coding/runtime/store.py", "runtime"),
    FileTask("src/eskill/code/hybrid.py", "src/vibe_coding/runtime/hybrid.py", "runtime"),
    FileTask("src/eskill/code/models.py", "src/vibe_coding/runtime/_legacy_models.py", "runtime"),
    # nl/ verbatim
    FileTask("src/eskill/vibe_coding/nl/__init__.py", "src/vibe_coding/nl/__init__.py", "nl"),
    FileTask("src/eskill/vibe_coding/nl/llm.py", "src/vibe_coding/nl/llm.py", "nl"),
    FileTask("src/eskill/vibe_coding/nl/prompts.py", "src/vibe_coding/nl/prompts.py", "nl"),
    # other vibe_coding modules with rewrites
    FileTask("src/eskill/vibe_coding/code_factory.py", "src/vibe_coding/code_factory.py", "code_factory"),
    FileTask(
        "src/eskill/vibe_coding/workflow_models.py", "src/vibe_coding/workflow_models.py", "workflow_models"
    ),
    FileTask(
        "src/eskill/vibe_coding/workflow_factory.py", "src/vibe_coding/workflow_factory.py", "workflow_factory"
    ),
    # NOTE: audit.py, facade.py, cli.py, __init__.py, workflow_engine.py are
    # hand-maintained in the standalone tree because they intentionally drop
    # the config-layer integration upstream still has. Do NOT add them here.
]


# ----------------------------------------------------------------- driver


def run(source: Path, dest: Path, check: bool) -> int:
    if not source.exists():
        print(f"error: source {source} does not exist", file=sys.stderr)
        return 2
    drift = 0
    for task in TASKS:
        src_file = source / task.src
        dst_file = dest / task.dst
        if not src_file.exists():
            print(f"warn: missing source {src_file} (skipped)")
            continue
        rewriter = REWRITERS[task.rewrite]
        new_text = rewriter(src_file.read_text(encoding="utf-8"))
        old_text = dst_file.read_text(encoding="utf-8") if dst_file.exists() else ""
        if old_text == new_text:
            continue
        if check:
            drift += 1
            diff = "".join(
                difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=str(dst_file),
                    tofile=f"{src_file} (rewritten)",
                    n=2,
                )
            )
            print(diff)
        else:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            dst_file.write_text(new_text, encoding="utf-8")
            print(f"wrote {dst_file.relative_to(dest)}")
    if check and drift:
        print(f"\n{drift} file(s) differ", file=sys.stderr)
        return 1
    if check:
        print("standalone is in sync with upstream")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Path to eskill-prototype root (default: ../eskill-prototype)",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=ROOT,
        help="Path to vibe-coding root (default: this script's repo)",
    )
    parser.add_argument("--check", action="store_true", help="Diff only, do not write")
    args = parser.parse_args()
    return run(args.source.resolve(), args.dest.resolve(), args.check)


if __name__ == "__main__":
    raise SystemExit(main())
