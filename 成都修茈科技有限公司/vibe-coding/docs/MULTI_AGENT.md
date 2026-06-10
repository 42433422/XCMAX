# Multi-Agent Orchestration

vibe-coding ships two coordinators that compose specialised LLM-backed
roles into bigger workflows than a single `ProjectVibeCoder` can
handle alone:

- **`MultiAgentOrchestrator`** — sequential pipeline:

  ```
  brief → Planner → (Researcher) → Coder → Reviewer
                              ↑                  │
                              └── revise loop ◄──┘
  ```

- **`BestOfNOrchestrator`** — fan out to *n* Coders in parallel, ask
  the Reviewer to score each result, commit only the highest-scored
  one. Useful when the brief admits multiple plausible approaches.

Both speak the same `AgentMessage` envelope and write to the same
`MessageBus`, so any UI / log can render the conversation as a chat
transcript.

## Quick start (sequential)

```python
from vibe_coding import VibeCoder, OpenAILLM
from vibe_coding.agent.orchestration import (
    MultiAgentOrchestrator,
    PlannerAgent, CoderAgent, ReviewerAgent, ResearcherAgent,
)

coder_facade = VibeCoder(llm=OpenAILLM(api_key="..."), store_dir="./data")
project_coder = coder_facade.project_coder("./my_project")

orch = MultiAgentOrchestrator(
    planner=PlannerAgent(llm=coder_facade.llm),
    coder=CoderAgent(project_coder=project_coder),
    reviewer=ReviewerAgent(llm=coder_facade.llm),
    researcher=ResearcherAgent(llm=coder_facade.llm),  # optional
    max_rounds=3,
)

result = orch.run("把 print() 全部改成 logger.info() 并补上对应测试")
print(result.success, result.rounds)
print(result.final_review.get("verdict"))
```

`result.messages` is the full conversation log — feed it into your UI,
log to a file, or replay it in tests.

## Best-of-N (parallel exploration)

```python
from vibe_coding.agent.orchestration import BestOfNOrchestrator, CoderAgent

# Spawn 3 coders that share a project_coder but compete on the same plan.
orch = BestOfNOrchestrator(
    planner=PlannerAgent(llm=coder_facade.llm),
    coders=[CoderAgent(project_coder=project_coder) for _ in range(3)],
    reviewer=ReviewerAgent(llm=coder_facade.llm),
)
result = orch.run("Refactor data layer to use SQLAlchemy 2.x")
print(result.final_patch["patch_id"], result.final_review["score"])
```

The reviewer assigns a 0-100 score; only the winning patch is reflected
in `result.final_patch`. The other attempts stay in `result.messages`
for post-mortem diff viewing.

## Roles

Every role implements the `AgentRole` Protocol — one method, `handle`,
that takes a message and returns the next message(s). You can subclass
or replace any of them:

| Role | Responsibility | Default Implementation |
| --- | --- | --- |
| `PlannerAgent` | NL brief → 1-5 concrete sub-tasks | LLM, JSON output |
| `CoderAgent` | Sub-task → `ProjectPatch` | Wraps `project_coder.edit_project` |
| `ReviewerAgent` | Patch → approve / revise / reject + score | LLM, JSON output |
| `ResearcherAgent` | Question → ≤500-word findings | LLM, optional |
| `TesterAgent` | Patch → suggested test cases | LLM, optional |

## Message envelope

```python
@dataclass
class AgentMessage:
    sender: str
    recipient: str
    kind: str               # plan / patch / approval / revise / failure / …
    content: dict           # payload — open vocabulary per ``kind``
    msg_id: str
    timestamp: float
    parent_id: str          # links replies back to their request
    summary: str
```

The `MessageBus` is single-process and append-only. For cross-machine
runs, subscribe a callback that streams every message into your queue
of choice (Redis Streams, NATS, etc.).

## Design notes

- Roles are stateless. All per-run state lives on the bus / inside the
  orchestrator's loop variables.
- Failures are first-class: a planner that returns malformed JSON
  emits a `failure` message and the orchestrator records it in
  `result.error`. No exceptions leak out of the run.
- Memory writes happen inside `CoderAgent` (via `ProjectVibeCoder`),
  not the orchestrator — so the same exemplar history powers both
  single-shot and multi-agent runs.
- The orchestrator does **no I/O of its own**. Everything goes through
  one of the supplied agents, so unit tests can swap in fakes
  trivially (`MockLLM` + `_StubProjectCoder`).
