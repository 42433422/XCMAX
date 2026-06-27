# Retort Engine

Retort is a blackhole-style external evolution engine.

- Main project: local folder.
- Absorption source: GitHub URL or local folder.
- Workflow: collect evidence, ask PaiBi LLM to score with the Retort prompt, clone/read the external project, generate absorption tasks, run the real `retort apply-absorption` CLI to change project code, then require another completed PaiBi LLM deep review before any score is shown.
- UI: dependency-free local blackhole interface.

Run:

```bash
PYTHONPATH=packages/retort_engine FHD/.venv/bin/python -m retort_engine.cli ui --host 127.0.0.1 --port 8790
```

Run one absorption cycle:

```bash
PYTHONPATH=packages/retort_engine FHD/.venv/bin/python -m retort_engine.cli absorb \
  --own-project packages/retort_engine \
  --github https://github.com/alibaba/open-code-review \
  --run-local-gates \
  --json

PYTHONPATH=packages/retort_engine FHD/.venv/bin/python -m retort_engine.cli self-evolve \
  --project packages/retort_engine \
  --run-local-gates
```

`absorb` is intentionally synchronous: the blackhole UI keeps running until the CLI has changed files and gates have returned. Use `--no-execute-absorption` only for dry task generation.

```bash
PYTHONPATH=packages/retort_engine FHD/.venv/bin/python -m retort_engine.cli apply-absorption \
  --payload-file packages/retort_engine/.retort/execution_requests/example.json \
  --json
```

Run a structured PR diff review from absorbed capabilities:

```bash
PYTHONPATH=packages/retort_engine FHD/.venv/bin/python -m retort_engine.cli review-diff \
  --diff-file /path/to/change.diff \
  --json
```

Retort does not treat self-questioning as completed absorption. Local code no longer produces scores; all scores must come from a completed PaiBi LLM deep review using the Retort prompt:

```bash
PYTHONPATH=packages/retort_engine FHD/.venv/bin/python -m retort_engine.cli record-proof \
  --project packages/retort_engine \
  --branch-diff-verified \
  --employee-execution-verified \
  --post-absorption-tests-passed \
  --merge-verified \
  --external-advantage-reassessed \
  --evidence "branch diff, employee result, post-merge gates, and external reassessment"
```
