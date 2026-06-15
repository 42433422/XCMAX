# vibe-coding

> **Standalone, self-contained Python package** that lets you turn any natural-
> language brief into a sandbox-validated, self-healing Python skill — and
> compose multiple skills into a complete workflow.

This package is the standalone twin of [`eskill.vibe_coding`](../eskill-prototype/src/eskill/vibe_coding)
inside the `eskill-prototype` project. The two stay in sync via the
`scripts/sync_from_eskill.py` helper, but `vibe-coding/` has zero dependency
on the `eskill` package — it carries all the runtime / sandbox / validator
machinery it needs in `src/vibe_coding/runtime/` so you can drop it into any
project (or copy the folder, branch off, and research alternative architectures
without touching the production tree).

## Install

```bash
cd vibe-coding
pip install -e ".[llm,test]"
```

## 30-second tour

```python
from vibe_coding import VibeCoder, MockLLM

coder = VibeCoder(llm=MockLLM([...]), store_dir="./data")

skill  = coder.code("把字符串反转")        # CodeSkill (sandbox-validated)
graph  = coder.workflow("天气查询员工 + 穿衣建议")  # multi-skill workflow
result = coder.execute(graph, {"city": "Beijing"})

coder.history(skill.skill_id)              # patch trail
coder.rollback(skill.skill_id, 1)          # one-click rollback
coder.report()                             # cross-skill health
```

In production, swap `MockLLM` for `OpenAILLM(api_key=...)`.

## Agent mode (project-aware editing)

vibe-coding can also operate as a **project-level coding agent** that reads
your existing codebase, generates multi-file patches, applies them
atomically and rolls back on failure:

```python
from vibe_coding import VibeCoder, OpenAILLM

coder = VibeCoder(llm=OpenAILLM(api_key=...), store_dir="./vibe_coding_data")

# Understand the project (incremental, cached)
index = coder.index_project("./my_project")
print(index.summary())

# Generate and apply a precise diff
patch = coder.edit_project("把所有 print() 换成 logger.info()", root="./my_project")
result = coder.apply_patch(patch, root="./my_project")

# Roll back if something breaks
coder.rollback_patch(patch.patch_id, root="./my_project")

# Iterative heal loop (P1: add a ToolRunner for real tool validation)
heal_result = coder.heal_project("修复 ImportError", root="./my_project", max_rounds=3)
```

CLI equivalents:

```bash
python -m vibe_coding --mock index --root .
python -m vibe_coding --mock edit "重命名 foo → bar" --root . --apply
python -m vibe_coding apply patch.json --root . --dry-run
python -m vibe_coding heal "修复测试" --root . --max-rounds 3

# Marketplace: package + publish a skill to MODstore
export MODSTORE_BASE_URL=https://modstore.example.com
export MODSTORE_ADMIN_TOKEN=...
python -m vibe_coding publish reverse-string --version 1.0.0 --price 0

# Web UI cockpit (http://127.0.0.1:8765)
python -m vibe_coding web

# JSON-RPC LSP-lite for editor plugins
python -m vibe_coding lsp
```

See `docs/AGENT_GUIDE.md` for the full tour, `docs/SANDBOX_DRIVERS.md` for
sandbox configuration and `docs/LANGUAGE_ADAPTERS.md` for writing new
language adapters (TypeScript / Vue / JSX adapters ship in tree).

## Differentiators vs. Trae and other AI IDEs

- Generated code passes the sandbox + every test case **before** you receive it
- Runtime failures auto-diagnose, AST-validate, sandbox-verify, then solidify a new version
- Strict import whitelist + forbidden-builtin AST guards (no `eval` / `exec` / `open`)
- Version history with one-call rollback (`PatchLedger`)
- Config layer + code layer coexist
- True end-to-end "AI-generated workflow": one brief → multi-node graph + all skills built and verified
- Domain guard rejects out-of-scope inputs from polluting LLM repair chains
- Brief-first two-step generation produces sharper code than single-shot

### Hardening (P0 / P1 / P2 follow-ups)

- **Path-traversal guard** (`agent/security/paths.py`) — every LLM-supplied
  path is normalised + validated before touching the disk; centralised so
  one fix covers the patch applier, sandbox driver, project coder and
  index builder.
- **Sandbox env scrub** (`agent/security/env.py`) — `command` jobs only
  inherit a curated allow-list (`PATH` / `HOME` / `LANG` / …); secrets like
  `OPENAI_API_KEY` no longer leak into spawned tools. `function` jobs run
  with `cwd=tempdir` and `stdin=DEVNULL`.
- **Tolerant LLM JSON parser** (`nl/parsing.py`) — strips fences, comments,
  trailing commas, smart quotes, BOM/zero-width chars, auto-balances
  truncated braces, recovers from chatter prefixes. Replaces ad-hoc parsers
  in `code_factory`, `workflow_factory`, `agent.coder`, `debug_reasoner`.
- **Hunk repair cascade** (`agent/patch/repair.py`) — strict → fuzzy
  anchors → unique old_text → leading-whitespace-tolerant matching, with
  a fallback to LLM-supplied full rewrite when every cascade fails.
- **Workflow conditions + retries** (`workflow_conditions.py`,
  `workflow_engine.py`) — edges support a safe expression language;
  per-node `retry_count` / `timeout_s`; `RunOptions` hooks for
  `on_node_start` / `on_node_complete` / `on_node_skip`.
- **Project domain guard** (`agent/domain.py`) — reject patches that
  touch paths outside `allowed_paths`, exceed `max_files_changed`, add
  forbidden imports, or fail any user-supplied predicate.
- **TypeScript / Vue / JSX adapters** (`agent/repo_index/adapters/`) —
  regex-based fallbacks (zero extra deps) covering JSX components,
  decorators, re-exports, default exports, Vue props/emits/slots, and
  template event handlers. The `agent-treesitter` extra swaps in
  tree-sitter when full fidelity matters.
- **Memory with failures** (`agent/memory/`) — `record_failure()`
  for "what not to do" exemplars; LRU pruning with `max_exemplars`;
  `last_used_at` tracking; tags + metadata for filtered retrieval.
- **Front-end toolchain** (`agent/tools/adapters/`) — `eslint`, `tsc`,
  `vitest`, `prettier` adapters share the same Protocol as `ruff` /
  `mypy` / `pytest`. Convenience factories `default_python_adapters()`,
  `default_javascript_adapters()`, `default_polyglot_adapters()`.
- **MODstore marketplace** (`agent/marketplace/`) — `SkillPackager` →
  `.xcmod` zip; `MODstoreClient` → admin catalog API; `SkillPublisher`
  ties them together so `coder.publish_skill(...)` is one call.
- **More sandbox drivers** (`agent/sandbox/`) — `WebContainerSandboxDriver`
  (proxy to a browser-side WebContainer for front-end workflows);
  `CloudSandboxDriver` with E2B / generic-HTTP backends for hosted
  execution; `MockSandboxDriver` for tests.
- **Multi-agent orchestration** (`agent/orchestration/`) —
  `MultiAgentOrchestrator` (Planner → Coder → Reviewer with revise
  loops) and `BestOfNOrchestrator` (parallel race + reviewer-picked
  winner). Pluggable `ResearcherAgent` / `TesterAgent` round out the
  cast.
- **Web UI + LSP-lite** (`agent/web/`) — FastAPI server with a single-
  page browser UI plus a JSON-RPC LSP-lite for editor plugins
  (VSCode / Trae / Cursor).

See `docs/P0_P1_CHECKLIST.md` for the full capability matrix.
Detailed guides:
[MARKETPLACE](docs/MARKETPLACE.md) ·
[MULTI_AGENT](docs/MULTI_AGENT.md) ·
[WEB_UI](docs/WEB_UI.md) ·
[SANDBOX_DRIVERS](docs/SANDBOX_DRIVERS.md) ·
[LANGUAGE_ADAPTERS](docs/LANGUAGE_ADAPTERS.md).

## Layout

```
vibe-coding/
├── src/vibe_coding/
│   ├── _internals/    # TriggerPolicy / EvolutionEvent / quality_report / Code* dataclasses
│   ├── runtime/       # CodeValidator + CodeSandbox + CodeSkillRuntime + Hybrid
│   ├── nl/            # LLM client + 4 prompts
│   ├── code_factory.py
│   ├── config_factory.py
│   ├── workflow_*.py
│   ├── audit.py
│   ├── facade.py      # VibeCoder
│   └── cli.py         # python -m vibe_coding ...
├── tests/
├── examples/
├── scripts/sync_from_eskill.py
└── docs/
```

## Sync from the prototype

If `eskill-prototype` evolves the upstream code, sync forward:

```bash
python scripts/sync_from_eskill.py
```

The script copies `eskill.vibe_coding.*` source into `src/vibe_coding/`,
rewrites the few imports that referred to `eskill.code`, `eskill.models`, and
`eskill.static_executor` so the standalone package stays self-contained.

See `docs/UPGRADE_GUIDE.md` for the full workflow.

## License

MIT — same as the upstream `eskill-prototype`.
