# Integration Guide

How to drop `vibe_coding` into another project without touching its existing
architecture.

## As a path dependency

Most clean approach for sibling projects:

```toml
# pyproject.toml of the consumer
[project]
dependencies = [
    "vibe-coding @ file:../vibe-coding",
]
```

Then:

```bash
pip install -e .
```

The consumer codebase imports from `vibe_coding` as if it were any third-party
library; no source files need to be copied.

## As a vendored copy

If the consumer cannot tolerate an external path:

```bash
cp -r vibe-coding/src/vibe_coding consumer/lib/vibe_coding
```

Then `from lib.vibe_coding import VibeCoder, MockLLM, ...` (adjust import
roots to taste). When upstream evolves, repeat the copy and run the
consumer's tests.

## With MODstore (or any FastAPI / Django service)

Pattern: keep the consumer's existing skill registry / runtime, *and* expose
a thin endpoint that delegates code-layer work to vibe-coding.

```python
# consumer_service/vibe_routes.py
from fastapi import APIRouter
from vibe_coding import VibeCoder, OpenAILLM

router = APIRouter(prefix="/api/vibe", tags=["vibe-coding"])

_coder = VibeCoder(
    llm=OpenAILLM(api_key=settings.openai_key),
    store_dir=settings.vibe_store_dir,
)

@router.post("/code")
def make_code_skill(brief: str):
    skill = _coder.code(brief)
    return {"skill_id": skill.skill_id, "active_version": skill.active_version}

@router.post("/workflow")
def make_workflow(brief: str):
    return _coder.workflow_with_report(brief).graph.to_dict()

@router.post("/run/{skill_id}")
def run(skill_id: str, payload: dict):
    return _coder.run(skill_id, payload).to_dict()

@router.post("/rollback/{skill_id}/{version}")
def rollback(skill_id: str, version: int):
    skill = _coder.rollback(skill_id, version)
    return {"skill_id": skill.skill_id, "active_version": skill.active_version}
```

The consumer's existing workflow engine remains the source of truth for
business workflows; vibe-coding only owns the *generated* code-layer skills
plus their per-skill self-healing loop. If the consumer wants to consume the
generated workflow as well, call `coder.workflow(brief)` and translate the
returned `VibeWorkflowGraph` into the consumer's own node model.

## Choosing between standalone and upstream

- **Standalone**: simpler dependency surface; code-layer only; ideal for
  research / prototypes / consumers that don't need the full eskill double-
  layer architecture.
- **Upstream `eskill.vibe_coding`**: same NL feature set plus config-layer
  (`ESkill`) integration, dual-layer `ESkillNodeWrapper`, and the full eskill
  audit / strategy stack. Pick this when you want every Skill node in your
  workflow to participate in the existing eskill self-healing ecosystem.

You can run both simultaneously: `eskill.vibe_coding.VibeCoder` for the
production tree, `vibe_coding.VibeCoder` (this package) as a sandbox to
research alternative prompts / retry strategies / patch generators without
touching production.

## Reference integration: MODstore_deploy

The sibling project [`MODstore_deploy`](../../MODstore_deploy/) is a
production reference of the patterns above. It wires vibe-coding into
**three production lines** simultaneously:

| Line | Surface | vibe-coding API |
|---|---|---|
| AI Mod authoring | `mod_employee_impl_scaffold.generate_mod_employee_impls_async` | `ProjectVibeCoder.heal_project` (after LLM-generated employees), `index_project` to cache the symbol table for the authoring page |
| AI Employees | `employee_executor._actions_real` handlers `vibe_edit` / `vibe_heal` / `vibe_code` | `VibeCoder.edit_project` + `apply_patch`, `heal_project`, `code` + `run` |
| Skills | `eskill_runtime._execute_logic` kinds `vibe_code` / `vibe_workflow`, canvas nodes `vibe_skill` / `vibe_workflow`, `script_agent.agent_loop.run_vibe_agent_loop` (alternate to `run_agent_loop`), workbench tab "AI 代码技能" | full surface: `code` + `run`, `workflow` + `execute`, `code_factory.repair`, `SkillPackager` + `MODstoreClient` for one-click publish |

Key implementation details worth borrowing:

- **One LLMClient bridge** instead of duplicating provider/key logic.
  MODstore's adapter wraps its existing `chat_dispatch` / `chat_dispatch_via_session` as a `LLMClient`
  ([`integrations/vibe_adapter.py:ChatDispatchLLMClient`](../../MODstore_deploy/modstore_server/integrations/vibe_adapter.py)).
  This keeps BYOK routing, quota counting, and provider catalog in one place.

- **Per-user `VibeCoder` cache** keyed on `(user_id, provider, model)` so each
  tenant gets isolated `store_dir`/`PatchLedger`, but multiple requests reuse the
  same indexes / skill store.

- **Path whitelist for project-level actions**.
  `vibe_edit` / `vibe_heal` MUST refuse roots outside `MODSTORE_TENANT_WORKSPACE_ROOT`
  (`ensure_within_workspace`); see the same module above.

- **In-process import + optional sub-app mount**.
  `vibe_coding.agent.web.create_app()` is mounted at `/api/vibe` only when
  `MODSTORE_ENABLE_VIBE_WEB=1`; the rest of the integration uses direct Python imports.

- **Graceful degradation on missing vibe-coding**.
  Every adapter call is guarded; if `import vibe_coding` fails it returns a
  structured `{"ok": false, "reason": "..."}` so the host service still boots and
  surfaces a clear error to the operator.

See [`MODstore_deploy/docs/VIBE_INTEGRATION.md`](../../MODstore_deploy/docs/VIBE_INTEGRATION.md)
for the full architecture diagram, environment variables, and operator runbook.
