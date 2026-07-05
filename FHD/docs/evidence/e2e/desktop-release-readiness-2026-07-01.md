# 桌面端全部功能测试记录（2026-07-01）

## 结论

当前代码的自动化测试闸门、full-stack P0、真实桌面后端、企业版 macOS 本地打包产物、以及干净用户目录 packaged app 启动均已通过。

正式对外上线口径：暂不通过。阻塞项是 macOS 发布面仍缺 Developer ID 签名/公证，且新生成的 `latest-mac.yml` 没有 Ed25519 二次签名；线上 `stable/enterprise/latest-mac.yml` 当前同样缺该签名。Windows 线上包本轮复核通过。

边界：本轮未上传新 macOS 包到公网，因为缺签名 metadata 会让打包版更新检查失败，直接同步会扩大线上风险。若上线门槛要求 0 warning，还需要继续清理 pytest 中既有 warning。

## 本轮关键修复

- 修复租户隔离测试默认上下文与 compat DB 原始 SQL 写入测试的 tenant scope，使业务写入 fail-closed 与旧测试模型兼容。
- 修复 Product/PurchaseUnit 仓储在 tenant filter 下的查询与批量写入路径。
- 修复 shipment event-primary 测试在 NeuroBus ready 分支的 async mock 设置。
- 修复 MODstore digest/employee SSOT 路径与 duty roster 派发表覆盖。
- 修复移动 relay 重复注册测试、auth 扩展路由 market profile mock、移动 admin duty roster 期望。
- 修复 NeuroBus bridge 把需要 `NeuroDomain.on()` 的 handler 当 `NeuroBus` handler 二次注册的问题；order/customer/payment/wechat 现在由 DomainRegistry 管理。
- 修复 `agentRunEvents.generated.ts` 生成的 TypeScript union 语法。
- 修复 full-stack P0 登录假通过：默认改为企业演示账号，严格要求 `/api/auth/login` 返回 `success: true`，并按 origin 缓存浏览器 cookie，避免触发登录限流。

## 测试流程与结果

### 后端

- `cd FHD && .venv/bin/python -m pytest -q`
  - `32988 passed, 29 skipped, 1 xpassed, 55 warnings in 390.78s`
- `cd FHD && .venv/bin/python -m pytest tests/test_neuro_bus_handler_registry.py tests/neuro/test_register_all_domains_complete.py -q`
  - `15 passed`
- 关键租户/仓储/移动/SSOT/route targeted 套件：
  - `1549 passed, 1 warning`
- compat DB + tenant scope focused：
  - `142 passed`

### 前端与桌面壳

- `cd FHD/frontend && npm test -- --run`
  - `Test Files 556 passed | 2 skipped (558)`
  - `Tests 9805 passed | 4 skipped (9809)`
- `cd FHD/frontend && npm run build:generic:strict`
  - 通过；仅 Vite large chunk warning。
- `cd FHD/desktop && npm run build`
  - 通过。
- `cd FHD && .venv/bin/python -m pytest tests/test_dev/test_neuro_bus_events_ssot.py -q`
  - `6 passed`

### Playwright / 真实桌面路径

- mock P0：
  - `npm run test:e2e:p0`
  - `8 passed, 6 skipped`
- full-stack P0（Vite 5001 + desktop FastAPI 17520 + 企业演示账号真实登录）：
  - `E2E_FULL_STACK=1 npm run test:e2e:p0`
  - `14 passed`
- 桌面模式 FastAPI：
  - `XCAGI_UVICORN_RELOAD=0 .venv/bin/python XCAGI/run.py --desktop --host 127.0.0.1 --port 17520 --data-dir /tmp/xcagi-e2e-desktop`
  - `/api/health` 返回 HTTP 200，`neuro.running=true`
  - NeuroBus bridge 启动日志不再出现 `handler register failed` / `NeuroBus has no attribute on`

### 真实 API 与交付 smoke

- 桌面 API 矩阵：
  - `35 total / 35 passed`
  - `critical_failed=[]`
  - `server_errors=[]`
- 负载/并发探针：
  - `.venv/bin/python scripts/loadtest/probe.py --base http://127.0.0.1:17520 --suite desktop-mods --workers 5 --total 20 --timeout 10`
  - `20/20` HTTP 200
- macOS 交付 smoke：
  - `cd FHD && bash scripts/dev/mac_deliverable_smoke.sh`
  - 通过：FastAPI health + deliverable-status

### 发布打包与远端核验

- 企业版 macOS 正式脚本第一轮：
  - `bash scripts/package/build-installer.sh 10.0.0 enterprise`
  - 失败原因：脚本默认使用系统 `python3`，本机为 Python 3.9.6；项目要求 `>=3.11`。
- 企业版 macOS 正式脚本第二轮：
  - `PYTHON=/Users/a4243342/Desktop/XCMAX/FHD/.venv/bin/python bash scripts/package/build-installer.sh 10.0.0 enterprise`
  - 后端 PyInstaller、企业版内置 mods、Electron ZIP 产物完成。
  - DMG 阶段首次失败：Electron Builder 从 GitHub 下载 `dmg-builder@1.2.0` 超时。
- DMG 补构建：
  - 手动从 npmmirror CDN 下载 `dmgbuild-bundle-arm64-75c8a6c.tar.gz`，SHA-256 校验为 `a785f2a385c8c31996a089ef8e26361904b40c772d5ea65a36001212f1fc25e0`。
  - `CUSTOM_DMGBUILD_PATH=.../dmgbuild npx electron-builder --mac dmg ...`
  - 通过，生成：
    - `release/xcagi-v10.0.0/enterprise/XCAGI-10.0.0-mac-arm64.dmg`，`296812021` bytes，SHA-256 `8c2ea6e78771798cc13955b8108b8df26a5e8b24036d3d7b303887ab525f1fcc`
    - `release/xcagi-v10.0.0/enterprise/XCAGI-10.0.0-mac-arm64.zip`，`290313414` bytes，SHA-256 `e2037a29d8d3f57a272de89b216ad61172ad23317de3dcc7c8eaa9b5ad200809`
    - `release/xcagi-v10.0.0/enterprise/latest-mac.yml`，`350` bytes，SHA-256 `dfd9d560cbb1c597c53dcad6bb378e396f2cefa9782112e4e2aa6a87686afbca`
- macOS DMG 校验：
  - `hdiutil verify release/xcagi-v10.0.0/enterprise/XCAGI-10.0.0-mac-arm64.dmg`
  - 通过：`checksum ... is VALID`
- packaged app 结构与启动：
  - `product-sku.json` 为 `{"sku":"enterprise","schema_version":1}`
  - 包内后端存在：`XCAGI.app/Contents/Resources/backend/xcagi-backend`
  - 临时 HOME + 独立端口 `17510` 干净启动通过：
    - `/api/health` 返回 healthy，`neuro.running=true`
    - `/api/platform-shell/deliverable-status` 返回 `success=true`、`product_sku=enterprise`、`edition=full`、`installed_mod_count=14`、`missing_mod_ids=[]`
- macOS 签名/Gatekeeper：
  - `codesign -dv` 显示 `Signature=adhoc`、`TeamIdentifier=not set`
  - `spctl --assess` 对 `.app` 不通过：`code has no resources but signature indicates they must be present`
  - `spctl --assess --type open` 对 `.dmg` 返回 `rejected`
- update metadata：
  - 本机缺 `XCAGI_UPDATE_ED25519_PRIVATE_KEY`，无法对新 `latest-mac.yml` 做 Ed25519 二次签名。
  - `desktop/updater.ts` 在打包版默认校验该签名；缺签名会导致检查更新失败。
- 远端公网核验（SSH `root@119.27.178.147`，只读检查，未上传）：
  - `/var/www/update/releases/stable/enterprise` 当前 macOS 线上包仍是 2026-06-29 版本：
    - DMG `270053526` bytes，SHA-256 `0888c6d90ea5f0b679ad4b0649cf53d935086eefee7a840694524a9c913e7ad5`
    - ZIP SHA-256 `4496811d92e19ddb734b6c12003c81f62a7a8c33a1150e703ba9fb89612412fd`
    - `latest-mac.yml` SHA-256 `be115c2beb83b1f1b2d3d506e882f2633791df33a083dc57035ea4e9ccbde9fd`
  - 线上 `latest-mac.yml` 无 `signature: ed25519:`。
  - 站内 HTTPS `curl --resolve xiu-ci.com:443:127.0.0.1` 对 `latest-mac.yml` 和 DMG 均返回 HTTP 200。
  - Windows enterprise 线上包复核通过：
    - `latest.yml` 有 `signature: ed25519:...`
    - EXE `133150395` bytes
    - 远端 `7z t` 识别为 `Type = Nsis`，结果 `Everything is Ok`

## 剩余风险

- pytest 仍有 55 个 warning，主要包括 FastAPI/TestClient deprecation、部分测试返回非 None、若干测试 mock 触发的 unawaited coroutine warning、JWT HMAC key length warning、event loop closed unraisable warning。
- Vite strict build 仍有 large chunk warning。
- macOS 缺 Developer ID 签名、公证与 Gatekeeper 通过证据。
- macOS `latest-mac.yml` 缺 Ed25519 二次签名；本机没有 `XCAGI_UPDATE_ED25519_PRIVATE_KEY`，不能安全签名并上传。
- 本轮没有上传新 macOS 包到远端；公网仍是 2026-06-29 的旧 macOS 包。

## 上线判断

按“本地代码、自动化测试、桌面真实运行、full-stack P0、企业版 packaged app 干净启动”口径：通过。

按“正式对外发布”口径：暂不通过。至少需要补齐 macOS Developer ID 签名/公证、用正式 Ed25519 私钥签名 `latest-mac.yml`、再上传并做公网下载/安装/更新复测后，才可以宣称正式上线。
