# Agent Mode Guide

vibe-coding ships in two modes:

- **Single-skill mode** — the original NL → sandbox-validated function flow
  (`VibeCoder.code()`, `workflow()`, `run()`). Unchanged. Continue to use it
  for self-healing single skills.
- **Project agent mode** — a project-aware coding agent (P0+ of the agent
  upgrade) that reads existing code, performs multi-file edits with anchored
  hunks, and applies them atomically with rollback. Backed by a hardened
  sandbox driver (subprocess by default, Docker when available).

Both modes share the same `VibeCoder` instance so you don't pay any extra
cost when you only need one of them. Agent code is lazy-imported under
`vibe_coding.agent` so legacy users never trigger it.

## 30-second tour

```python
from vibe_coding import VibeCoder, OpenAILLM

coder = VibeCoder(
    llm=OpenAILLM(api_key=...),
    store_dir="./vibe_coding_data",
)

# 1. Understand the project (incremental hash-based scan)
index = coder.index_project("./my_project")
print(index.summary())  # → files / symbols / languages

# 2. Generate a multi-file patch from a brief
patch = coder.edit_project(
    "把所有 print() 调用换成 logger.info()",
    root="./my_project",
)
print(patch.summary, patch.stats())

# 3. Apply atomically (any conflict rolls everything back)
result = coder.apply_patch(patch, root="./my_project")
print("applied:", result.applied, "files:", [f.path for f in result.files])

# 4. Roll back when something goes wrong downstream
coder.rollback_patch(patch.patch_id, root="./my_project")
```

## CLI

The CLI matches the Python API closely:

```bash
python -m vibe_coding --mock index --root .
python -m vibe_coding --mock edit "重命名所有 foo 为 bar" --root . --apply
python -m vibe_coding apply patch.json --root . --dry-run
python -m vibe_coding heal "修一下 ImportError" --root . --max-rounds 3
```

Every agent command supports:

- `--root` — project root (default `.`)
- `--active-file PATH` — currently focused file
- `--cursor LINE` or `--cursor LINE:COL` — cursor position
- `--notes TEXT` — free-form note injected into the prompt
- `--no-auto-context` — skip the `git status` / `git diff` auto context

When run inside a Git working tree the auto-context picks up dirty files and
a one-page `git diff --stat HEAD`, so the agent already knows what you've
been editing without any IDE plugin.

## ProjectPatch JSON shape

The applier and the prompts agree on this exact schema:

```json
{
  "patch_id": "kebab-case-string",
  "summary": "one-line summary",
  "rationale": "2-4 sentences why",
  "edits": [
    {
      "path": "rel/path.py",
      "operation": "modify",
      "hunks": [
        {
          "anchor_before": "<= 3 lines context\nstrictly verbatim\n",
          "old_text": "exact substring being replaced\n",
          "new_text": "replacement\n",
          "anchor_after": "<= 3 lines after context\n"
        }
      ]
    },
    { "path": "rel/new.py", "operation": "create", "contents": "..." },
    { "path": "rel/old.py", "operation": "delete" },
    { "path": "rel/from.py", "operation": "rename", "new_path": "rel/to.py" }
  ]
}
```

Hunks must locate via the strict pass first (anchor + old_text + anchor
matches verbatim). If the strict pass fails, the applier retries once with
`fuzzy_lines` (default 10) of tolerance — anchors must still appear nearby,
just not in the exact original positions. Anything beyond that raises
`PatchConflict` and the whole patch rolls back.

## Sandbox drivers

Two drivers are wired into the agent:

- `SubprocessSandboxDriver` — always available, reuses the legacy
  `runtime.sandbox.CodeSandbox` for single-function jobs and adds a generic
  `command` mode for tool runs.
- `DockerSandboxDriver` — opt-in (`docker` CLI must be on PATH and the
  daemon reachable). Runs each job inside a fresh container with
  `--network=none --read-only --cap-drop=ALL --memory --cpus --pids-limit`,
  giving real isolation even when the LLM-generated code goes off the
  rails.

Pick one explicitly with `create_default_driver(prefer="docker")` or let the
default `auto` mode choose Docker when available, subprocess otherwise.

## P0 vs P1 vs P2

- **P0** — code-understanding engine, multi-file edits + precise diff,
  hardened sandbox driver, facade and CLI integration.
- **P1** — context awareness (richer `AgentContext`), debug reasoning
  (`DebugReasoner`), tool integration (ruff / mypy / pytest).
- **P2 — shipping now** — TypeScript / Vue / JSX adapters with full
  symbol vocabulary; ESLint / TSC / Vitest / Prettier tool adapters;
  WebContainer + cloud sandbox drivers; MODstore marketplace
  publishing; multi-agent orchestration; Web UI + LSP-lite for editor
  plugins.

See `docs/P0_P1_CHECKLIST.md` for the full capability matrix and
`docs/MARKETPLACE.md` / `docs/MULTI_AGENT.md` / `docs/WEB_UI.md` for
the new add-ons.
