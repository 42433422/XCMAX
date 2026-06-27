# Retort Engine

Retort is a blackhole-style external evolution engine.

- Main project: local folder.
- Absorption source: GitHub URL or local folder.
- Workflow: assess overlap and depth, clone/read the external project, generate absorption tasks, apply an absorption shock, then keep scores capped until real closed-loop proof is recorded.
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

Retort does not treat self-questioning as completed absorption. Scores stay capped until all proof gates are recorded:

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
