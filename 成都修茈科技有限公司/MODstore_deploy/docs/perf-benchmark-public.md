# MODstore 与 FHD（XCAGI）性能基线（公开）

本文档为仓库内**公开性能基线**的单一事实来源；更新前请重跑 k6 并同步修改本页表格与日期。勿将真实账号密码、JWT 或内网未脱敏地址写入本文件。

## 元数据


| 项目                     | 值                                                                                                                                                                                                                                              |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 文档日期                   | 2026-05-04                                                                                                                                                                                                                                     |
| MODstore_deploy Git（短） | `70fd951`                                                                                                                                                                                                                                      |
| FHD Git（短）             | `aa9a961`                                                                                                                                                                                                                                      |
| k6 版本                  | 0.54.0（容器镜像 `grafana/k6:0.54.0`）                                                                                                                                                                                                               |
| 本次执行环境说明               | 本机 Windows + Docker Desktop。被测目标为 `[perf/local_mock_server.py](../perf/local_mock_server.py)`（5 ms 人为延迟）。**这是脚本可运行性与采集形态验证，不是生产/预发容量基线**；详情见 `[perf/results/2026-05-04-local-mock/REPORT.md](../perf/results/2026-05-04-local-mock/REPORT.md)` |
| 历史记录                   | 2026-05-03 `62b5a39`：`127.0.0.1:8000` 无监听，全部连接失败，仅作为「采集失败形态」记录保留                                                                                                                                                                               |


## 1. MODstore 全链路（`perf/full_link_smoke.js`）

### 1.1 运行参数


| 项                                         | 值                            |
| ----------------------------------------- | ---------------------------- |
| `K6_STAGE`                                | `smoke`（2 VU、约 1 分钟，与脚本默认一致） |
| `BASE_URL`                                | `http://127.0.0.1:8000`      |
| `WS_URL` / `TEST_EMAIL` / `TEST_PASSWORD` | 未配置（无登录与 WebSocket 子场景压测）    |
| `ENABLE_LLM` / `ENABLE_RAG`               | 未开启（默认）                      |


### 1.2 k6 摘要（本次）

本轮**未对 `full_link_smoke.js` 重新跑全链路**（脚本依赖登录、市场、支付、WebSocket 等多接口；本机 mock 只覆盖 `/api/health` 等，跑全链路不会得到有意义的全绿摘要）。如需更新本节，请在预发同栈打开 `BASE_URL` / `WS_URL` / `TEST_EMAIL` / `TEST_PASSWORD` 后重跑并替换下表。


| 指标                         | 值      |
| -------------------------- | ------ |
| `http_reqs`                | 待测（预发） |
| `http_req_failed`          | 待测     |
| `checks`                   | 待测     |
| `iterations`               | 待测     |
| `vus_max`                  | 待测     |
| `modstore_business_errors` | 待测     |


### 1.3 复现命令

在 `MODstore_deploy` 仓库根目录：

```bash
K6_STAGE=smoke k6 run perf/full_link_smoke.js
```

Windows（已安装 k6 时）：

```powershell
$env:K6_STAGE='smoke'; k6 run perf/full_link_smoke.js
```

指定环境与账号（勿提交密钥）：

```bash
BASE_URL=https://your-host \
WS_URL=wss://your-host \
TEST_EMAIL=loadtest@example.com \
TEST_PASSWORD='***' \
K6_STAGE=smoke \
k6 run perf/full_link_smoke.js
```

### 1.4 Grafana（可选）

本次未连接可观测栈，无面板截图。生产/预发跑完后请在 `MODstore Overview` 记录 FastAPI p95、支付代理 p95、JVM heap、Hikari、5xx，并追加到本节或链接到内部 wiki。

---

## 2. FHD / XCAGI API 脚本（`FHD/scripts/loadtest`）

### 2.1 路由对齐说明（2026-05-03）

脚本已与当前 FastAPI 路由对齐（`config.js`）：


| 逻辑名                        | 路径                           |
| -------------------------- | ---------------------------- |
| health                     | `GET /api/health`            |
| catalog（原 products 键名保留）   | `GET /api/mod-store/catalog` |
| liveness（原 shipments 键名保留） | `GET /health/liveness`       |
| auth（仅 `stress.js`）        | `POST /api/auth/login`       |


### 2.2 k6 摘要：`smoke.js`（本次，2026-05-04，本地 mock）


| 指标                            | 值                                                                     |
| ----------------------------- | --------------------------------------------------------------------- |
| `http_reqs`                   | 150                                                                   |
| `http_req_failed`             | 0%（0/150）                                                             |
| `checks`                      | 100%（150/150）                                                         |
| `iterations`                  | 75                                                                    |
| `vus`                         | 5（恒定 30s）                                                             |
| `http_req_duration` p95 / max | 13.73 ms / 21.55 ms                                                   |
| 阈值                            | `http_req_duration p(99)<500ms`、`http_req_failed rate<0.05` — **均通过** |


完整原始输出与摘要 JSON 见 `[perf/results/2026-05-04-local-mock/](../perf/results/2026-05-04-local-mock/REPORT.md)`。

### 2.3 k6 摘要：`load.js`（本次，2026-05-04，本地 mock）

阶梯：10 → 50 → 50 → 10 VU，3 分钟。


| 指标                                  | 值                                                           |
| ----------------------------------- | ----------------------------------------------------------- |
| `http_reqs`                         | 2982                                                        |
| `http_req_failed`                   | 3.28%（98/2982，全部为客户端 `dial: i/o timeout`）                   |
| `checks`                            | 96.71%（2884/2982）                                           |
| `iterations`                        | 994                                                         |
| `vus_max`                           | 50                                                          |
| `http_req_duration` p95 / max（成功请求） | 8.66 ms / 22.18 ms                                          |
| 阈值                                  | `http_req_duration p(99)<1000ms`、`error_rate<0.1` — **均通过** |


98 个失败发生在 50 VU 高峰，是 mock（Python `ThreadingHTTPServer`）拒绝新连接造成的；用真实 FastAPI/uvicorn 上游不会出现这种形态。仅作为「脚本与阶梯能跑通」的证据，不是被测系统的容量结论。

### 2.4 复现命令

在 `FHD` 仓库根目录（已安装 k6）：

```bash
k6 run -e BASE_URL=http://127.0.0.1:8000 scripts/loadtest/smoke.js
k6 run -e BASE_URL=http://127.0.0.1:8000 scripts/loadtest/load.js
k6 run -e BASE_URL=http://127.0.0.1:8000 scripts/loadtest/stress.js
```

未安装 k6 时，可用 Docker 镜像 + 本仓 mock 复现 2.2 / 2.3：

```bash
python MODstore_deploy/perf/local_mock_server.py --port 18000 --latency-ms 5 &
docker run --rm -v "$(pwd)/FHD/scripts/loadtest:/loadtest:ro" \
  -e BASE_URL=http://host.docker.internal:18000 \
  grafana/k6:0.54.0 run /loadtest/smoke.js
```

---

## 3. 口径声明（对外引用 QPS / 延迟数字时必读）

仓库内**没有**任何脚本曾跑出过 ≥ 2000 持续 RPS 的结果，也没有针对 0.6 s 页面加载（FCP/LCP）的 Lighthouse 或 `web-vitals` 报告。简历、PPT 或对外材料中若出现「2000 QPS」「0.6 s 加载」等具体数字：


| 数字                               | 当前状态                                                      | 引用前必须做                                                         |
| -------------------------------- | --------------------------------------------------------- | -------------------------------------------------------------- |
| 2000 QPS                         | **目标 / 未验证**。当前可验证基线见 §1、§2 表格                            | 在预发同栈跑 `K6_STAGE=step` 至 50–200 VU，将摘要回填本文档并记录 Grafana p95/连接池 |
| 0.6 s 加载                         | **目标 / 未验证**。后端 GET p95 不等于「页面加载」                         | 在目标环境用 Lighthouse / `web-vitals` 测 FCP / LCP，并写入仓库内单一事实来源      |
| `/api/health` p95 < 300 ms 等 SLO | 见 `[docs/sre-operating-model.md](sre-operating-model.md)` | SLO 是承诺值，不能作为「已实测」对外引用                                         |


任何不在 §1 / §2 / `[perf/results/](../perf/results/)` 中可定位的数字，都按 **目标，未验证** 处理；引用方式建议为「目标 X，预发同栈复测后以仓库内基线为准」。

---

## 4. 正式基线回填检查清单

- 目标 `BASE_URL` 可访问，`GET /api/health` 返回 200。
- MODstore：`K6_STAGE=smoke` 通过后再按需跑 `step` / `soak`。
- FHD：`smoke.js` 全绿后再跑 `load.js` / `stress.js`。
- 将本节以上各表的 N/A/失败率替换为**成功连接**下的 p95/p99、错误率与迭代次数。
- 同步更新 FHD 仓库内 `docs/reports/capacity-planning.md` 中对应表格（与本文件常见同盘布局：`[../../../FHD/docs/reports/capacity-planning.md](../../../FHD/docs/reports/capacity-planning.md)`；若 FHD 检出位置不同则改用组织内链接）。

