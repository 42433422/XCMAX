# 2026-05-04 本地 mock 压测报告

本目录是一次**本地 mock + dockerized k6** 跑出的可复现压测记录，用来证明：

1. `FHD/scripts/loadtest` 与 `MODstore_deploy/perf/full_link_smoke.js` 中的脚本能正常运行并产出真实指标；
2. 已有的 [`docs/perf-benchmark-public.md`](../../../docs/perf-benchmark-public.md) 不再仅是「目标端口无监听 → 100% 失败」的占位结果；
3. 任何对外或简历中出现的吞吐 / 延迟数字都需要在本目录或上游基线中找到对应记录，否则按「目标，未验证」处理。

> 这不是生产或预发容量基线。Mock 是 `perf/local_mock_server.py`（Python stdlib `ThreadingHTTPServer`，5 ms 人为延迟），单进程 GIL 限制让它在 ~50 VU 时本身就是瓶颈；这里观察到的 i/o timeout 是**压测客户端打爆了 mock**，不是被测系统的容量结论。

## 元数据

| 项 | 值 |
| --- | --- |
| 日期 | 2026-05-04 |
| MODstore_deploy Git（短） | `70fd951` |
| FHD Git（短） | `aa9a961` |
| k6 | `grafana/k6:0.54.0`（容器内执行） |
| Mock | `perf/local_mock_server.py --port 18000 --latency-ms 5` |
| 客户端 → 服务地址 | `http://host.docker.internal:18000`（Docker 容器内）/ `http://127.0.0.1:18000`（probe.py） |
| 主机 | Windows 10 + Docker Desktop |

## 1. probe.py（FHD 提供，纯 stdlib）

复现命令（`MODstore_deploy` 工作目录）：

```bash
python ../FHD/scripts/loadtest/probe.py \
  --url http://127.0.0.1:18000/api/health \
  --workers 50 --total 1000
```

结果（见 [`probe-health.txt`](probe-health.txt)）：

| 指标 | 值 |
| --- | --- |
| `total` | 1000 |
| `workers` | 50 |
| `wall_s` | 1.713 |
| `rps` | 583.8 |
| `status_codes` | `{200: 1000}` |
| `latency_ms p50 / p95 / p99` | 15.76 / 524.74 / 1027.46 |

> p95/p99 偏大主要是 Python `urllib` + 50 线程在 GIL 下抖动 + mock 自身 5 ms 延迟，不是被测系统问题。`probe.py` 适合做基线 QPS 与可达性快检，不适合代替 k6 的容量评估。

## 2. k6 + FHD `smoke.js`

复现命令：

```bash
docker run --rm \
  -v "<repo>/FHD/scripts/loadtest:/loadtest:ro" \
  -e BASE_URL=http://host.docker.internal:18000 \
  grafana/k6:0.54.0 run /loadtest/smoke.js
```

结果（见 [`k6-fhd-smoke.txt`](k6-fhd-smoke.txt)）：

| 指标 | 值 |
| --- | --- |
| `http_reqs` | 150 |
| `http_req_failed` | 0%（0/150） |
| `checks` | 100%（150/150） |
| `iterations` | 75 |
| `vus` | 5（恒定 30s） |
| `http_req_duration` p95 / max | 13.73 ms / 21.55 ms |
| 阈值 | `p(99)<500ms`、`failed<5%` — **均通过** |

这是与 [`docs/perf-benchmark-public.md` 第 2.2 节](../../../docs/perf-benchmark-public.md) 同一脚本下，**第一次** 在本仓库内得到全绿的 k6 摘要。

## 3. k6 + FHD `load.js`（阶梯：10 → 50 → 50 → 10 VU）

复现命令：

```bash
docker run --rm \
  -v "<repo>/FHD/scripts/loadtest:/loadtest:ro" \
  -v "<repo>/MODstore_deploy/perf/results/2026-05-04-local-mock:/out" \
  -e BASE_URL=http://host.docker.internal:18000 \
  grafana/k6:0.54.0 run \
  --summary-export=/out/k6-fhd-load-summary.json \
  /loadtest/load.js
```

结果（见 [`k6-fhd-load.txt`](k6-fhd-load.txt)、[`k6-fhd-load-summary.json`](k6-fhd-load-summary.json)）：

| 指标 | 值 |
| --- | --- |
| `http_reqs` | 2982 |
| `http_req_failed` | 3.28%（98/2982，全部为 `dial: i/o timeout`） |
| `checks` | 96.71%（2884/2982） |
| `iterations` | 994 |
| `vus_max` | 50 |
| `http_req_duration` p95 / max（成功） | 8.66 ms / 22.18 ms |
| 阈值 | `p(99)<1000ms` 通过；`error_rate<0.1` 通过 |

98 个失败全部是高峰期 mock 拒绝新连接造成的客户端 `i/o timeout`。**这是 mock 服务的限制**，不是被测系统的容量结论；用真实 FastAPI/uvicorn 上游重跑同一脚本不会出现这种形态的失败。

## 4. 与对外宣称数字的对账

| 对外说法 | 仓库内可验证基线 | 处理 |
| --- | --- | --- |
| 「2000 QPS」 | 无任何脚本本仓内跑出过 ≥ 2000 持续 RPS 的结果 | 简历 / 对外 PPT 必须改为「目标」，并附「待预发同栈复测」字样；详情见 [`docs/perf-benchmark-public.md`](../../../docs/perf-benchmark-public.md) 口径声明节 |
| 「0.6 s 加载」 | mock 上 GET p95 ≈ 14 ms（5 VU），不能等同于真实页面加载 | 同上；真实「加载 0.6 s」需要前端页面级别（FCP/LCP）测量，需 Lighthouse / `web-vitals` 在目标环境复测 |

## 5. 下一步

- 在预发（同等服务规格）启动完整 Compose 栈后，重跑同样三组（`probe.py` / `smoke.js` / `load.js`），将本目录的「mock」标签替换成「预发 + 版本号」目录。
- 评估是否在 CI 中保留 `smoke.js` 的 5VU/30s 跑作为发布门禁（与 [`docs/sre-operating-model.md`](../../../docs/sre-operating-model.md) 容量管理节对齐）。
- 如需对外/对内引用 QPS / 延迟数字，先在 [`docs/perf-benchmark-public.md`](../../../docs/perf-benchmark-public.md) 的口径声明节登记一条「数字 ↔ 报告」映射，再对外引用。
