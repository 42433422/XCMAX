"""``python -m vibe_coding`` command-line entry point (standalone build)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .facade import VibeCoder
from .nl.llm import MockLLM, OpenAILLM


def _build_llm(args: argparse.Namespace) -> Any:
    if args.mock:
        return MockLLM(
            {
                "default": json.dumps(
                    {
                        "skill_id": "demo",
                        "name": "demo",
                        "domain": "demo",
                        "function_name": "demo",
                        "source_code": "def demo(value=''):\n    return {'echo': str(value)}",
                        "signature": {
                            "params": ["value"],
                            "return_type": "dict",
                            "required_params": [],
                        },
                        "dependencies": [],
                        "test_cases": [
                            {
                                "case_id": "happy",
                                "input_data": {"value": "ping"},
                                "expected_output": {"echo": "ping"},
                            }
                        ],
                        "quality_gate": {"required_keys": ["echo"]},
                        "domain_keywords": ["demo"],
                    }
                )
            }
        )
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY") or ""
    if not api_key:
        print("error: --api-key or OPENAI_API_KEY required (use --mock for offline)", file=sys.stderr)
        raise SystemExit(2)
    return OpenAILLM(api_key=api_key, model=args.model, base_url=args.base_url)


def _make_coder(args: argparse.Namespace) -> VibeCoder:
    llm = _build_llm(args)
    return VibeCoder(llm=llm, store_dir=args.store_dir, llm_for_repair=not args.mock)


def _cmd_code(args: argparse.Namespace) -> int:
    skill = _make_coder(args).code(args.brief, mode=args.mode, skill_id=args.skill_id)
    print(json.dumps(skill.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_workflow(args: argparse.Namespace) -> int:
    report = _make_coder(args).workflow_with_report(args.brief)
    print(
        json.dumps(
            {
                "workflow_id": report.workflow_id,
                "graph": report.graph.to_dict(),
                "code_skills_created": report.code_skills_created,
                "warnings": report.warnings,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    coder = _make_coder(args)
    try:
        input_data = json.loads(args.input_json)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(input_data, dict):
        print("error: input must be a JSON object", file=sys.stderr)
        return 2
    run = coder.run(args.skill_id, input_data)
    print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_rollback(args: argparse.Namespace) -> int:
    skill = _make_coder(args).rollback(args.skill_id, args.version)
    print(
        json.dumps(
            {"skill_id": skill.skill_id, "active_version": skill.active_version},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    print(json.dumps(_make_coder(args).report(args.skill_id), ensure_ascii=False, indent=2))
    return 0


def _cmd_history(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            [r.to_dict() for r in _make_coder(args).history(args.skill_id)],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            {"code_skills": [s.skill_id for s in _make_coder(args).list_code_skills()]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


# ----------------------------------------------------------------- agent (P0)


def _make_context(args: argparse.Namespace) -> "Any | None":
    """Best-effort :class:`AgentContext` from CLI flags + git status."""
    from .agent.context import AgentContext

    ctx = AgentContext.from_git(args.root) if getattr(args, "auto_context", True) else AgentContext()
    if getattr(args, "active_file", None):
        ctx.active_file = args.active_file
    cursor = getattr(args, "cursor", None)
    if cursor:
        if ":" in cursor:
            line_str, col_str = cursor.split(":", 1)
        else:
            line_str, col_str = cursor, "0"
        try:
            ctx.cursor_line = int(line_str)
            ctx.cursor_column = int(col_str)
        except ValueError:
            print(f"warning: ignoring invalid --cursor {cursor!r}", file=sys.stderr)
    notes = getattr(args, "notes", None)
    if notes:
        ctx.notes = notes
    return ctx if ctx.to_dict() else None


def _cmd_index(args: argparse.Namespace) -> int:
    coder = _make_coder(args).project_coder(args.root)
    index = coder.index_project(refresh=args.refresh)
    print(json.dumps(index.summary(), ensure_ascii=False, indent=2))
    return 0


def _cmd_edit(args: argparse.Namespace) -> int:
    coder = _make_coder(args).project_coder(args.root)
    patch = coder.edit_project(
        args.brief,
        context=_make_context(args),
        focus_paths=list(args.focus or []),
    )
    if args.apply:
        result = coder.apply_patch(patch, dry_run=False)
        print(
            json.dumps(
                {"patch": patch.to_dict(), "apply": result.to_dict()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if result.applied else 1
    if args.dry_run:
        result = coder.apply_patch(patch, dry_run=True)
        print(
            json.dumps(
                {"patch": patch.to_dict(), "dry_run": result.to_dict()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if result.applied else 1
    print(json.dumps(patch.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    from .agent.patch import ProjectPatch

    coder = _make_coder(args).project_coder(args.root)
    raw_path = Path(args.patch_file)
    if not raw_path.is_file():
        print(f"error: patch file not found: {raw_path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(raw_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in patch: {exc}", file=sys.stderr)
        return 2
    patch = ProjectPatch.from_dict(data)
    result = coder.apply_patch(patch, dry_run=args.dry_run)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.applied else 1


def _cmd_heal(args: argparse.Namespace) -> int:
    coder = _make_coder(args).project_coder(args.root)
    result = coder.heal_project(
        args.brief,
        context=_make_context(args),
        max_rounds=args.max_rounds,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.success else 1


# ----------------------------------------------------------------- marketplace


def _cmd_publish(args: argparse.Namespace) -> int:
    coder = _make_coder(args)
    base_url = args.base_url or os.environ.get("MODSTORE_BASE_URL", "")
    admin_token = args.admin_token or os.environ.get("MODSTORE_ADMIN_TOKEN", "")
    if not (base_url and admin_token):
        print(
            "error: --base-url and --admin-token (or MODSTORE_* env vars) are required",
            file=sys.stderr,
        )
        return 2
    try:
        result = coder.publish_skill(
            args.skill_id,
            base_url=base_url,
            admin_token=admin_token,
            version=args.version,
            name=args.name,
            description=args.description,
            price=args.price,
            artifact=args.artifact,
            industry=args.industry,
            verify_ssl=not args.no_verify_ssl,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"error: publish failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.published or result.dry_run else 1


# ----------------------------------------------------------------- web / lsp


def _cmd_web(args: argparse.Namespace) -> int:
    from .agent.web import run_server

    coder = _make_coder(args)
    print(f"vibe-coding web ui listening on http://{args.host}:{args.port}", file=sys.stderr)
    run_server(host=args.host, port=args.port, coder=coder, log_level=args.log_level)
    return 0


def _cmd_lsp(args: argparse.Namespace) -> int:
    """Run the JSON-RPC LSP-lite server over stdin/stdout for editor plugins."""
    from .agent.web import LSPServer

    coder = _make_coder(args)
    LSPServer(coder).serve_stdio()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vibe_coding",
        description="Standalone vibe coding — NL to self-healing skills",
    )
    parser.add_argument("--store-dir", default="./vibe_coding_data")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--mock", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    code = sub.add_parser("code", help="generate a CodeSkill")
    code.add_argument("brief")
    code.add_argument("--mode", choices=["direct", "brief_first"], default="brief_first")
    code.add_argument("--skill-id", default=None)
    code.set_defaults(func=_cmd_code)

    wf = sub.add_parser("workflow", help="generate a complete workflow")
    wf.add_argument("brief")
    wf.set_defaults(func=_cmd_workflow)

    run = sub.add_parser("run", help="execute a code skill")
    run.add_argument("skill_id")
    run.add_argument("input_json")
    run.set_defaults(func=_cmd_run)

    rb = sub.add_parser("rollback", help="rollback to a previous version")
    rb.add_argument("skill_id")
    rb.add_argument("version", type=int)
    rb.set_defaults(func=_cmd_rollback)

    rep = sub.add_parser("report", help="patch / evolution stats")
    rep.add_argument("skill_id", nargs="?", default=None)
    rep.set_defaults(func=_cmd_report)

    hist = sub.add_parser("history", help="chronological patch list")
    hist.add_argument("skill_id")
    hist.set_defaults(func=_cmd_history)

    ls = sub.add_parser("list", help="list known code skills")
    ls.set_defaults(func=_cmd_list)

    # -------------------------------------------------------------- agent (P0)
    idx_cmd = sub.add_parser("index", help="build / refresh the project RepoIndex")
    idx_cmd.add_argument("--root", default=".")
    idx_cmd.add_argument("--refresh", action="store_true", help="ignore the cached index")
    idx_cmd.set_defaults(func=_cmd_index)

    edit_cmd = sub.add_parser("edit", help="generate a multi-file ProjectPatch from a NL brief")
    edit_cmd.add_argument("brief")
    edit_cmd.add_argument("--root", default=".")
    edit_cmd.add_argument("--apply", action="store_true", help="apply the patch instead of just printing it")
    edit_cmd.add_argument("--dry-run", action="store_true", help="run the applier in dry-run mode")
    edit_cmd.add_argument("--focus", action="append", default=[], help="files to surface to the LLM (repeatable)")
    edit_cmd.add_argument("--active-file", default=None)
    edit_cmd.add_argument("--cursor", default=None, help="LINE or LINE:COL")
    edit_cmd.add_argument("--notes", default=None)
    edit_cmd.add_argument(
        "--no-auto-context",
        dest="auto_context",
        action="store_false",
        default=True,
        help="skip the git-status auto context",
    )
    edit_cmd.set_defaults(func=_cmd_edit)

    apply_cmd = sub.add_parser("apply", help="apply a saved ProjectPatch JSON")
    apply_cmd.add_argument("patch_file")
    apply_cmd.add_argument("--root", default=".")
    apply_cmd.add_argument("--dry-run", action="store_true")
    apply_cmd.set_defaults(func=_cmd_apply)

    heal_cmd = sub.add_parser("heal", help="iterative edit + apply + (P1) tool validation loop")
    heal_cmd.add_argument("brief")
    heal_cmd.add_argument("--root", default=".")
    heal_cmd.add_argument("--max-rounds", type=int, default=3)
    heal_cmd.add_argument("--active-file", default=None)
    heal_cmd.add_argument("--cursor", default=None)
    heal_cmd.add_argument("--notes", default=None)
    heal_cmd.add_argument("--no-auto-context", dest="auto_context", action="store_false", default=True)
    heal_cmd.set_defaults(func=_cmd_heal)

    # ------------------------------------------------------------- marketplace
    pub = sub.add_parser(
        "publish", help="package a skill and upload it to a MODstore deployment"
    )
    pub.add_argument("skill_id")
    pub.add_argument("--base-url", default="", help="MODstore origin (env: MODSTORE_BASE_URL)")
    pub.add_argument("--admin-token", default="", help="admin access token (env: MODSTORE_ADMIN_TOKEN)")
    pub.add_argument("--version", default="")
    pub.add_argument("--name", default="")
    pub.add_argument("--description", default="")
    pub.add_argument("--price", type=float, default=0.0)
    pub.add_argument("--artifact", default="mod", choices=["mod", "employee_pack"])
    pub.add_argument("--industry", default="通用")
    pub.add_argument("--no-verify-ssl", action="store_true")
    pub.add_argument("--dry-run", action="store_true", help="package only; skip upload")
    pub.set_defaults(func=_cmd_publish)

    # --------------------------------------------------------------- web / lsp
    web_cmd = sub.add_parser(
        "web", help="run the vibe-coding Web UI / API on host:port"
    )
    web_cmd.add_argument("--host", default="127.0.0.1")
    web_cmd.add_argument("--port", type=int, default=8765)
    web_cmd.add_argument("--log-level", default="info")
    web_cmd.set_defaults(func=_cmd_web)

    lsp_cmd = sub.add_parser(
        "lsp", help="speak JSON-RPC over stdio for editor plugin integration"
    )
    lsp_cmd.set_defaults(func=_cmd_lsp)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def main_entry() -> int:
    """``project.scripts`` entry point: ``vibe-coding ...``."""
    return main()


if __name__ == "__main__":
    raise SystemExit(main())
