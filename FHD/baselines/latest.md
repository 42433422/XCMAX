# 四套基线 — 真实测量报告

- 采集时间(UTC):`2026-06-21T17:34:48Z`
- Git:`feat/quality-to-9@4a6aaefdd`  ·  平台:`darwin/arm64`
- 由 `FHD/scripts/baseline/measure.py` 自动生成;数字均来自真实产物,非估算。

## 速览(对比上次快照)

| 指标 | 当前 | 环比 |
|---|---:|---|
| 桌面 .app 体积 | 618.36 MB |  (±0) |
| 桌面可立即削减(P0) | 64.14 MB | — |
| 手机 APK 体积 | 26.68 MB |  (±0) |
| 前端 vue-dist 体积 | 56.30 MB |  (±0) |

## ① 包体积基线 — 桌面

**FHD/release/_electron-staging/mac-arm64/XCAGI.app** = **618.36 MB**

| 构成 | 体积 |
|---|---:|
| Python 后端(PyInstaller 冻结) | 296.79 MB |
| Electron Frameworks(Chromium 运行时,基本固定) | 262.80 MB |
| 前端 frontend(extraResource) | 56.31 MB |
| app.asar(主进程代码) | 1.70 MB |

**双打包浪费:**
- 前端 vue-dist 被打包两次(后端内嵌 + frontend extraResource) → 可去 **56.31 MB**(serve 路径是后端内嵌副本(loadURL→FastAPI);frontend extraResource 仅 cache-hash fallback,可去)

**P0 可立即削减合计 64.14 MB → 预计降到 554.21 MB:**
- mypy(冻结包死代码,运行时零 import):7.84 MB
- frontend 重复打包:56.31 MB

**后端大件(P1/P2 瘦身候选):** resources 60.47 MB, templates 56.29 MB, pandas 16.85 MB, libpython3.11.dylib 16.33 MB, PIL 11.35 MB, cryptography 10.85 MB, psycopg_binary 9.51 MB, lxml 8.64 MB, mypy 7.84 MB, pdfminer 7.82 MB

## ① 包体积基线 — 手机

**Android APK** `release/packages-v10.0.0/enterprise/XCAGI-Enterprise-Android-10.0.0.apk` = **26.68 MB**
  · lib 20.92 MB, dex 3.44 MB, assets 867.49 KB, resources.arsc 792.00 KB, res 433.60 KB, other 45.87 KB, kotlin 10.22 KB, AndroidManifest.xml 6.23 KB, META-INF 1.46 KB

**Harmony HAP** = 261.42 KB

## ② 启动耗时基线

桌面:_no_run_captured_ — 从终端启动一次桌面 app 复现埋点:cd FHD/desktop && npm run dev,关注 stdout 的 [xcagi-desktop] startup {...}

手机:adb shell am start -W -n com.xiuci.xcagi.mobile/.MainActivity | grep TotalTime

## ③ 更新包基线(全量 vs 差量)

| 产物 | 全量 | blockmap | 支持增量 |
|---|---:|---:|:--:|
| XCAGI-10.0.0-mac-arm64.zip | 313.94 MB | 314.76 KB | ✅ |

> blockmap 已生成 → electron-updater 在生成版 provider 下会自动只下增量块;下一步应实测一次跨版本更新的真实下载字节(本工具暂以全量为基线)。

## ④ 运行时性能基线 — 前端 bundle

**FHD/templates/vue-dist** 总 **56.30 MB** · JS 4.11 MB(gzip 1.31 MB) · CSS 629.06 KB(gzip 131.86 KB) · 114 个 JS chunk

入口 chunk(启动关键路径):`index-irOobsCK.js` 784.84 KB(gzip 251.07 KB)

**最大 chunk:**
- transformers.web-6PbSn4MM.js:903.58 KB(gzip 232.65 KB)
- index-irOobsCK.js:784.84 KB(gzip 251.07 KB)
- KittenAnalyzerView-Bmnid_7o.js:583.82 KB(gzip 197.47 KB)
- xlsx-BLGkKAvn.js:420.17 KB(gzip 138.66 KB)
- YuangongStitchFullView-CQ0TY_bq.js:239.04 KB(gzip 78.73 KB)
- InternalCustomerServiceView-CGbWk64R.js:98.19 KB(gzip 29.08 KB)

**重资产(P1 应改按需下载,不进基础包/启动路径):**
- ONNX Runtime WASM(离线 TTS):20.60 MB
- yuangong 数据/fixtures:25.58 MB
- 懒加载大块 transformers.web-6PbSn4MM.js(随包发布但多数用户不触发):903.58 KB
- 懒加载大块 xlsx-BLGkKAvn.js(随包发布但多数用户不触发):420.17 KB

> vite/build.js 无 manualChunks;入口 chunk + 重资产是 P1 抓手。

