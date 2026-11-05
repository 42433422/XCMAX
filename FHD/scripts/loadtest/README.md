# Load tests (k6)

| Script | Purpose |
|--------|---------|
| `smoke.js` | Real HTTP health/ping; P95 < 200ms, P99 < 500ms, no failed checks |
| `business_regression.py` | Synthetic IM SQL counts, vector allocation and CSV RSS at two sizes |
| `validate_evidence.py` | Reject absent reports/raw samples, wrong commit identities or failed budgets |
| `stress.js` | Ramp stress |
| `tier_c_smoke.js` | Tier C ramp to 200 VU |
| `tier_c_sustained.js` | Tier C 1000 RPS sustained |
| `tier_c_chat_streams.js` | Tier C concurrent chat SSE |

The performance workflow runs nightly/manually and for changes to the gate itself.
It builds the production UI, measures a 3000ms shell budget and 500ms real HTTP
health budget, and keeps the longer observation timeout separate from pass/fail.
Authentication is mocked only for the isolated UI shell case; this scope is
recorded in its attachment. P95/P99 use actual HTTP observations, never a fixed
`/api/sla/report` response. These local regressions do not establish production
capacity or Windows/macOS performance.

Run from `FHD/` with an isolated local API and dependencies installed:

```bash
mkdir -p performance-results
export BASE_URL=http://127.0.0.1:5000
export SOURCE_SHA="$(git rev-parse HEAD)"
python scripts/loadtest/business_regression.py
k6 version > performance-results/k6-version.txt
k6 run --out json=performance-results/k6-samples.jsonl scripts/loadtest/smoke.js
```

`business_regression.py` uses fresh subprocesses and temporary synthetic datasets:
100/1000 private conversations with a fixed 50-row page and <=6 SQL statements;
1000/10000 256-dimensional vectors with top_k=5 and <=10MiB traced allocations;
10000/100000 12-column CSV rows with <=64MiB sampled RSS growth. It validates all
rows are preserved and can be traversed again. Exact SQLite retrieval remains
O(ND); the memory budget does not claim ANN performance. All timings are recorded,
while count/memory assertions reduce dependence on shared-runner CPU noise.

The workflow records Python/dependency versions, k6/Node versions, source SHA,
input sizes, raw HTTP points and frontend measurements in `performance-results/`.
Its artifact path is **FHD/performance-results/** from the repository root;
`defaults.run.working-directory` does not affect upload-artifact. Missing files,
failed thresholds, skipped UI checks or mismatched source identities fail the
workflow. Negative controls verify that old 4x/6x/20s budget relaxations cannot pass.

Full capacity exercises retain their separate protocols:

```bash
k6 run scripts/loadtest/tier_c_smoke.js
k6 run scripts/loadtest/tier_c_sustained.js -e TIER_C_RPS=500 -e TIER_C_DURATION=2m
k6 run -e STREAM_CONCURRENCY=50 scripts/loadtest/tier_c_chat_streams.js
```
