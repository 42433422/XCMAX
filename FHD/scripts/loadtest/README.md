# Load tests (k6)

| Script | Purpose |
|--------|---------|
| `smoke.js` | Light smoke |
| `stress.js` | Ramp stress |
| `tier_c_smoke.js` | Tier C ramp to 200 VU |
| `tier_c_sustained.js` | Tier C 1000 RPS sustained |
| `tier_c_chat_streams.js` | Tier C concurrent chat SSE |

```bash
export BASE_URL=http://127.0.0.1:5000
k6 run scripts/loadtest/tier_c_smoke.js
k6 run scripts/loadtest/tier_c_sustained.js -e TIER_C_RPS=500 -e TIER_C_DURATION=2m
k6 run -e STREAM_CONCURRENCY=50 scripts/loadtest/tier_c_chat_streams.js
```

Evidence output: copy k6 summary to `docs/evidence/tier-c/`.
