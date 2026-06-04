# 性能冒烟 / 负载脚本

| 工具 | 脚本 | CI |
|------|------|-----|
| **k6** | `smoke.js`（PR 门禁）、`load.js`（1k/2k/5k QPS）、`stress.js` | [`.github/workflows/performance-smoke.yml`](../../.github/workflows/performance-smoke.yml)（PR 经 `test.yml` → `performance-gate` 调用） |
| **Locust** | [`../../XCAGI/tools/locustfile.py`](../../XCAGI/tools/locustfile.py) | 本地 / 压测环境手动 |

```bash
# 本地 k6（需先启动 API：python XCAGI/run.py）
export BASE_URL=http://127.0.0.1:5000
k6 run scripts/loadtest/smoke.js
```
