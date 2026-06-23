# 桌面/手机 性能 · 体积 · 自更新 路线图(数据驱动)

> 配套真实基线:`FHD/baselines/latest.md`(由 `scripts/baseline/measure.py` 自动生成)。
> 本文只写**决策与排序**,数字一律以 `latest.md` 为准,不在此处复制硬编码数字以免漂移。
> 方法论:**先量 → 摘果子 → 再量证明 Δ**。每条目标完成的判据 = 重跑基线、`latest.md` 速览表环比列出现 ▼。

## 核心洞察(决定一切排序)

各层**变更频率差几个数量级**,但今天打成一个单体、全量更新:

| 层 | 变更频率 | 真实体积(见 latest.md) | 更新策略应是 |
|---|---|---|---|
| Electron 外壳 + Chromium | 几乎不变 | ~263MB(基本不可压) | 罕见,走大差量 |
| Python 运行时 + 依赖 | 很少变 | ~297MB(含大量可瘦身) | 较罕见,差量 |
| Python 应用代码 | 常变 | (在后端内) | 差量 |
| **前端 vue-dist(代码部分)** | **很常变** | **代码仅 ~4MB JS / 1.3MB gzip** | **小包热更,免重启** |
| **前端重资产(ONNX/yuangong)** | 几乎不变、且多数用户不用 | **~46MB(占 vue-dist 82%)** | **按需下载,根本不进基础包** |
| 业务配置/mods/行业预设 | 最常变 | (resources ~60MB) | 动态下发 |

**结论:一次前端单行修复,今天逼用户下 ~314MB。** 「SKU裁剪 + 秒级启动 + 增量热更」本质是同一件事——**按变更频率拆层**。

---

## P0 — 建基线 + 零风险快赢 ✅(本轮已落地)

- ✅ 四套基线测量工具 `scripts/baseline/measure.py` + 首份真实报告 `baselines/latest.md`。
- ✅ **mypy 排除**(`xcagi_backend.spec` desktop_excludes):冻结包死代码,运行时零 import。
- ✅ **前端去重**(`electron-builder.yml`):后端已内嵌 vue-dist 且为 HTTP serve 路径,删掉单独的 `frontend` extraResource。
- ⏳ **发版前冒烟门**:`cd FHD/desktop && npm run pack` 后跑 `measure.py`,确认 .app ▼~64MB 且应用正常启动(读取安全性已逐一核查:`desktopInitialUrl` 纯 HTTP、`readFrontendCacheKey` 兜底优雅降级)。

> 两处改动只在**下次构建**生效;`latest.md` 的 `removable_now` 已预测 ▼~64MB(-10.4%)。

---

## P1 — 结构性改造(按真实杠杆排序)

### P1-1 重资产外置 / 按需下载 〔最大单点杠杆〕
ONNX-WASM + yuangong fixtures + transformers/xlsx 大块**移出 vue-dist**,首次使用时下载并缓存(ONNX 已走浏览器 Cache API,见 `frontend/src/utils/offlineTts.ts`)。
- 效果:vue-dist ~56MB → ~10MB;桌面包(已去重后单份)再省内嵌的同一批 ~46MB;**前端热更包从 56MB → ~10MB(gzip ~2MB)**,这是「秒级热更」可行的前提。
- 触点:`frontend/vite/staticCopy.js` / 构建产物拆分、资产取数 helper、一个 `assets-manifest.json`。

### P1-2 前端热更脱钩 Python 后端 〔秒级热更 / 高频层独立发版〕
前端作为**独立版本化层**:`frontend-manifest.json`(version+hash),启动时主进程比对更新服务器,下载 ~10MB 增量到 `userData`,从那里 serve;失败回退内嵌副本。让最高频的前端层不再绑后端整包。
- 依赖 P1-1(小 payload 才有意义)。触点:`desktop/main.ts`(serve 源切换 + 拉取)、更新服务器目录约定。

### P1-3 首屏不阻塞后端 〔秒级启动 / 干掉「分钟级」根因〕
今天 `createWindow` 在 `show()` **之前** `await waitForBackendHealth`(超时上限 120–180s)。
改为:**先出窗 + 轻量 splash/shell**(由主进程静态资源提供,不经 Python 后端),后端健康后再加载真实应用、流式点亮。冷启不再卡窗。
- 触点:`desktop/main.ts:600-674` createWindow 次序 + 一个 splash 资产。配合 P2 后端懒加载路由进一步压冷启。

### P1-4 手机推送更新 → 应用内升级 〔用户明确要的「推送更新」〕
`JPushReceiver` 已接收;打通:服务端发版 → 推送 → 应用内升级弹窗(`AppViewModel.UpdatePrompt` 已有)→ 后台下载 APK → `PackageInstaller` 应用内安装。当前仅「启动轮询 + 跳商店链接」。
- 触点:`mobile-android` push→update 链路;服务端版本元数据(`min/latest_android_version` 已有)。

### P1-5 实测差量更新,补全基线③
构建 vN+1,对 vN 跑一次真实更新,抓**真实增量字节**,确认 electron-updater differential 生效(blockmap 已生成,大概率已工作但未测),回填 `measure.py` 的 `measured_differential_bytes`。

---

## P2 — 深水区

- **PyInstaller 深瘦身**:审计 pandas(~17MB)、psycopg_binary(~9.5MB,桌面是否需 PG?多走 sqlcipher)、lxml、pdfminer 的运行时真实使用,排除/懒加载未用项。预计可再省 30–50MB。
- **后端冷启瘦身**:懒加载 FastAPI 路由 / 延迟重模块 import,直接压缩 P1-3 里后端就绪时间。
- **手机 OTA/差量**:bsdiff 差量 APK 或 Play In-App-Update;native Kotlin 无 JS-bundle 热更,故走差量包而非热更。
- **桌面 updater 企业级**:灰度(%-rollout)、强制版本门、启动失败自动回滚(当前 CHANGELOG 宣称但仅设计,`updater.ts` 未实现)。

---

## 怎么验收每一步

```bash
python3 FHD/scripts/baseline/measure.py     # 改前
# ...落地一个条目...
cd FHD/desktop && npm run pack               # 或重建相关产物
python3 FHD/scripts/baseline/measure.py     # 改后,看 latest.md 速览表环比 ▼
```
没有 ▼ 的「优化」= 没摘到果子。
