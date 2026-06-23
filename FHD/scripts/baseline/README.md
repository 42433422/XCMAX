# 四套基线 (Four Baselines)

> 从「凭感觉优化」转向「数据驱动优化」的度量底座。
> 先量，再改，再量 —— 每个优化都用真实字节数证明,不靠散文里的 `~0.8s` / `Lighthouse 95+`。

## 四套基线是什么

| # | 基线 | 量什么 | 当前抓手 |
|---|---|---|---|
| ① | **包体积** `package_size` | 桌面 `.app` 分层构成、手机 APK/HAP、双打包浪费、后端大件 | 桌面 618MB → P0 可立即削 64MB |
| ② | **启动耗时** `startup` | 桌面 `[xcagi-desktop] startup {...}` 埋点;手机 `am start -W` 冷启 | 首屏阻塞在后端健康检查 = 「分钟级」根因 |
| ③ | **更新包** `update_size` | 全量 zip/exe vs 差量 blockmap,是否支持增量下载 | blockmap 已生成,待实测跨版本真实增量 |
| ④ | **运行时性能** `runtime_perf` | 前端 `vue-dist` 体积/分块/gzip/重资产/入口 chunk | 代码仅 4MB JS;56MB 中 82% 是按需重资产 |

## 怎么跑

```bash
# 测全部 + 写快照 + 出报告 + 与上次 diff
python3 FHD/scripts/baseline/measure.py

# 只打印不落盘(CI 干跑 / 临时核对)
python3 FHD/scripts/baseline/measure.py --no-write

# 只测某一套
python3 FHD/scripts/baseline/measure.py --only runtime_perf
```

仅依赖 Python 标准库,任何机器/CI 都能跑。产物缺失时对应基线记 `status=missing` 并给出构建提示,绝不崩。

## 它读哪些真实产物

- 桌面包:`FHD/release/**/*.app`(electron-builder 产物)
- 桌面更新:`FHD/release/xcagi-v*/**/*.zip|*.exe` + 同名 `.blockmap`
- 手机包:`release/**/*Android*.apk`、`*.hap`
- 前端:`FHD/templates/vue-dist`(`npm run build` 产物)

→ 没有产物就先构建;基线必须测真实字节,不接受估算。

## 输出在哪

- `FHD/baselines/latest.md` —— 人读报告(每次覆盖,提交它看趋势)
- `FHD/baselines/latest.json` —— 最近一次机读快照(diff 的基准)
- `FHD/baselines/snapshots/<UTC>.json` —— 历史快照(每次追加,可回溯任意时点)

## 数据驱动的闭环

```
   measure ──▶ 看 latest.md 的「P0 可立即削减 / 重资产 / 入口 chunk」
      ▲                              │
      │                              ▼
   re-measure ◀── 改一处(去 mypy / 去重 / 拆 chunk / 资产外置)── 看「环比」列证明 Δ
```

每落一个优化,重跑一次,`latest.md` 顶部「速览」表的**环比**列会用 ▼ 标出真实削减量。这就是「摘果子」有没有摘到的客观判据。
