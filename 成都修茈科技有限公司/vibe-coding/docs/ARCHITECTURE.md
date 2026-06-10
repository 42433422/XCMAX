# Architecture

The standalone `vibe-coding` package mirrors the upstream
`eskill.vibe_coding` subpackage but ships everything it needs in tree.

## Module map

```
vibe_coding/
├── _internals/         # TriggerPolicy / EvolutionEvent / quality_report / Code* models
├── runtime/            # CodeValidator + CodeSandbox + CodeSkillRuntime + ...
├── nl/                 # LLMClient + 4 prompts
├── code_factory.py     # NL → CodeSkill (sandbox-validated)
├── config_factory.py   # synced from upstream; not used standalone
├── workflow_models.py  # VibeWorkflowGraph / Node / Edge
├── workflow_factory.py # NL → multi-skill workflow
├── workflow_engine.py  # code-layer-only runner
├── audit.py            # PatchLedger
├── facade.py           # VibeCoder
└── cli.py              # python -m vibe_coding
```

## Data flow

```mermaid
flowchart TB
  brief["NL brief"] --> facade["VibeCoder"]
  facade --> wf["NLWorkflowFactory"]
  wf --> cf["NLCodeSkillFactory per skill"]
  cf --> ast["CodeValidator AST"]
  cf --> sb["CodeSandbox subprocess"]
  sb -->|"failure → LLM repair"| ast
  sb -->|"pass"| store["JsonCodeSkillStore"]
  wf --> graph["VibeWorkflowGraph"]
  graph --> exec["VibeWorkflowEngine"]
  exec --> rt["CodeSkillRuntime\nfailure → solidify v2"]
  rt --> store
  store --> ledger["PatchLedger\nhistory / rollback / report"]
```

## Standalone vs upstream

| Concern | Upstream `eskill.vibe_coding` | Standalone `vibe_coding` |
| --- | --- | --- |
| Self-healing runtime | `eskill.code.CodeSkillRuntime` | `vibe_coding.runtime.CodeSkillRuntime` (copied + import-rewritten) |
| Models / TriggerPolicy / quality | `eskill.models` / `eskill.static_executor` | `vibe_coding._internals` (lifted) |
| Config-layer Skill | `ESkill` / `ESkillRuntime` (full support) | not vendored — `VibeCoder.config_skill()` raises |
| `ESkillNodeWrapper` integration | optional | not available |
| Tests | mirror in `tests/test_vibe_coding_*.py` | mirror minus config-layer tests |

When upstream evolves, run `python scripts/sync_from_eskill.py` to refresh
`runtime/`, `nl/`, `code_factory.py`, `workflow_models.py`,
`workflow_factory.py` and the `_legacy_models.py` placeholder. Other modules
are hand-maintained because they intentionally drop config-layer pieces.
