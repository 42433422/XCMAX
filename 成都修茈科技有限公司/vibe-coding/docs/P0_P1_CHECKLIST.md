# P0 / P1 Checklist (vs Trae and similar AI IDEs)

A capability matrix to make the differentiation explicit. "Standalone" refers
to this `vibe-coding/` package; "Upstream" refers to `eskill.vibe_coding` in
the prototype.

## P0 — must ship to be called "vibe coding"

| Capability | Trae | Standalone | Upstream |
| --- | :---: | :---: | :---: |
| NL → Python code generation | yes | yes | yes |
| Auto execute generated code | yes | yes | yes |
| Auto-run test cases against generated code (sandbox) | no | yes | yes |
| Auto-repair failing code via LLM with diff feedback | no | yes | yes |
| AST safety check (import whitelist + forbidden builtins) | weak | yes | yes |
| Subprocess sandbox with timeout / mem limit | no | yes | yes |
| Version snapshot per repair (immutable) | no | yes | yes |

## P1 — decides whether the system is competitive

| Capability | Trae | Standalone | Upstream |
| --- | :---: | :---: | :---: |
| Domain guard rejects out-of-scope inputs | no | yes | yes |
| Quality gate (required keys / min_length / regex) | no | yes | yes |
| Regression test on every patch | no | yes | yes |
| Config layer + Code layer coexist | no | no (code only) | yes |
| Workflow orchestration | partial | yes | yes |
| Dual-layer architecture (Employee + Skill) | no | no | yes (`ESkillNodeWrapper`) |
| One-shot NL → multi-skill workflow | partial | yes | yes |
| Patch ledger + one-click rollback | no | yes | yes |
| Brief-first two-stage generation | no | yes | yes |

## Agent upgrade — 11-capability acceptance matrix

The headline capabilities of the project-aware agent (see
`docs/AGENT_GUIDE.md`). Phases match the agent rollout plan, so you can read
this column-by-column to know what's currently shipped.

| # | Capability | Module | P0 | P1 | P2 | P3 |
| :---: | --- | --- | :---: | :---: | :---: | :---: |
| 1 | Code-understanding engine | `agent/repo_index/` | yes (Python) | — | yes (TS / Vue / JSX / decorators / Vue props/emits/slots) | **yes** (real tree-sitter when extra installed) |
| 2 | Multi-file atomic operations | `agent/patch/applier.py` | yes | — | — | — |
| 3 | Precise diff (no whole-file rewrites) | `agent/patch/differ.py` + hunk prompts | yes | hunk-cascade fallback | — | — |
| 4 | True sandbox isolation | `agent/sandbox/` + `agent/security/` | yes (subprocess + Docker) | env scrub + path guard | + WebContainer + Cloud + Mock | **yes** (cgroups CPU/memory/swap, ulimits, tmpfs cap) |
| 5 | Context awareness | `agent/context.py` | basic (auto git context) | full (recent edits, IDE injection, focus ranking) | — | — |
| 6 | Debug reasoning | `agent/debug_reasoner.py` | — | yes | — | — |
| 7 | Tool integration | `agent/tools/` (ruff / mypy / pytest) | — | yes | yes (+eslint, +tsc, +vitest, +prettier) | — |
| 8 | Learning & memory | `agent/memory/` | — | — | yes (success + failure exemplars) | **yes** (cross-project KB + embeddings + auto-promote) |
| 9 | Domain guard (project-level) | `agent/domain.py` | — | — | yes | — |
| 10 | Workflow conditions / retries | `workflow_conditions.py`, `workflow_engine.py` | — | yes | — | — |
| 11 | Tolerant LLM JSON parser | `nl/parsing.py` | yes | — | — | — |
| 12 | Marketplace publishing | `agent/marketplace/` | — | — | yes (CodeSkill → MODstore catalog) | — |
| 13 | Multi-agent orchestration | `agent/orchestration/` | — | — | yes (Planner / Coder / Reviewer + best-of-N) | — |
| 14 | Web UI / IDE integration | `agent/web/` | — | — | yes (FastAPI server + LSP-lite for plugins) | — |
| 15 | Multi-LLM provider support | `nl/providers/` | — | — | — | **yes** (Qwen / Zhipu / Moonshot / DeepSeek / Anthropic + factory) |
| 16 | Autonomous tool-using agent | `agent/react/` | — | — | — | **yes** (ReAct loop + ToolRegistry + 12 builtin tools) |
| 17 | Advanced workflow orchestration | `agent/workflow_advanced/` | — | — | — | **yes** (parallel / dynamic spawn / event triggers / async) |
| 18 | Observability | `agent/observability/` | — | — | — | **yes** (JSON logs + spans + metrics + Prometheus + OTel-compat) |

Notes:

- The agent layer is **lazy-loaded**; legacy `VibeCoder.code()` /
  `workflow()` / `run()` callers do not import it.
- `VibeCoder` gains `index_project / edit_project / apply_patch /
  rollback_patch / heal_project` methods that delegate to
  `ProjectVibeCoder`.
- `heal_project` accepts a `tool_runner` argument today but skips the
  validation phase when none is provided. Plug in the P1 `ToolRunner` once
  it lands and the same call site starts validating each round.

## Why this matters

Generation alone (Trae's lane) hands the user a draft they still have to
verify. The vibe-coding flow goes two big steps further:

1. Every single-skill artefact has already executed your test cases inside
   an isolated subprocess, and runtime failures during deployment trigger an
   automatic diagnose → LLM-repair → AST-validate → sandbox-verify →
   solidify pipeline.
2. Every project-level edit is anchored, atomic and rollback-able. The same
   sandbox driver layer that runs single-skill code can run real linters /
   type checkers / test runners against the patched workspace, so the
   "healing" loop closes against the *actual* tools your project relies on.

For the upstream tree, the dual-layer architecture extends this to entire
employees: when one Skill node solidifies a new version, the bridge can fan
out and adjust trust / strategy on the owning Employee. The standalone tree
keeps things simple (code layer only) — it's the right entry point if you're
researching the loop or embedding it into a project that doesn't already
depend on eskill.
