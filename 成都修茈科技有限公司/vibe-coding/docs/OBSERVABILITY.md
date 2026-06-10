# Observability — logs, traces, metrics

vibe-coding ships three minimal observability primitives, all
zero-dep so they import cleanly anywhere:

- `StructuredLogger` — JSON-line logs with run / span context baked in.
- `Tracer` — span-based tracing (OpenTelemetry semantic conventions).
- `MetricsRegistry` — counters / gauges / histograms with a Prometheus
  text exposition.

Use `instrument(coder)` to wire all three to a `VibeCoder` instance —
every public method gets a span + a log + a metric without the caller
having to thread context manually.

## Quick start

```python
from vibe_coding import VibeCoder, create_llm
from vibe_coding.agent.observability import instrument

coder = VibeCoder(llm=create_llm("qwen-max"), store_dir="./data")
obs = instrument(coder)                    # logger / tracer / metrics

skill = coder.code("Reverse a string")     # auto-logged + traced + counted

# Inspect what we recorded:
print(obs.metrics.to_prometheus())
spans = obs.tracer.exporters[0].all()
for s in spans:
    print(s.name, s.duration_ms, s.status)
```

## What gets recorded

Every wrapped method emits:

- A span named `vibe.<method>` with `vibe.component=vibe_coder` /
  `vibe.method=<name>` attributes.
- A log record `{"event":"action.start"|"action.end"|"action.error"}`
  carrying the same trace/span ids.
- Counters `vibe_coder_action_total{method=…}` /
  `vibe_coder_action_errors_total{method=…, error=…}`.
- A histogram `vibe_coder_action_duration_ms{method=…}` (default
  buckets cover 5ms → 60s).

The default method list covers `code`, `workflow`, `run`, `execute`,
`index_project`, `edit_project`, `apply_patch`, `heal_project`,
`publish_skill`, etc. Pass `methods=("code", "edit_project")` to wrap
only a subset.

## ReAct agent integration

```python
from vibe_coding.agent.react import ReActAgent, builtin_tools
from vibe_coding.agent.observability import instrument_react_agent

agent = ReActAgent(llm=coder.llm, tools=builtin_tools(root="./proj"))
instrument_react_agent(agent, obs)
```

Each step now produces:

- A log record `agent.react.step` with the tool name + duration.
- A counter `agent_react_step_total{tool=...}`.
- A histogram `agent_react_step_duration_ms{tool=...}`.

## Exporters

```python
from vibe_coding.agent.observability import (
    StructuredLogger, Tracer,
    InMemoryTraceExporter, OTelTraceExporter,
)

# Send spans to a real OTel pipeline when the SDK is installed:
tracer = Tracer(exporters=[InMemoryTraceExporter(), OTelTraceExporter()])

# JSON logs to a file, one line per record:
def to_file(line: str) -> None:
    with open("./vibe.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
logger = StructuredLogger(writer=to_file, level="info")
```

Set `VIBE_LOG_LEVEL=warning` and `VIBE_OTEL_ENABLED=true` to switch
the process-wide defaults without code changes.

## Prometheus

The metrics registry produces text-format exposition out of the box:

```python
print(obs.metrics.to_prometheus())
```

Wire it to the bundled FastAPI Web UI (`vibe_coding.agent.web`) by
mounting an extra `/metrics` route:

```python
from fastapi import Response
from vibe_coding.agent.web import create_app

app = create_app(coder=coder)

@app.get("/metrics")
async def metrics() -> Response:
    return Response(obs.metrics.to_prometheus(), media_type="text/plain")
```

## Counter / histogram cheat sheet

| Metric | Type | Labels |
| --- | --- | --- |
| `vibe_coder_action_total` | counter | `method` |
| `vibe_coder_action_errors_total` | counter | `method`, `error` |
| `vibe_coder_action_duration_ms` | histogram | `method` |
| `agent_react_step_total` | counter | `tool` |
| `agent_react_step_duration_ms` | histogram | `tool` |

Custom dashboards: register your own counter / gauge / histogram on
`obs.metrics` and they round-trip through the same Prometheus output:

```python
fail_counter = obs.metrics.counter("my_app_fail_total", description="...")
fail_counter.inc(1, labels={"reason": "rate_limited"})
```
