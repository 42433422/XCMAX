# release_train 深度闭环 Runbook

> **目标**：03:15 归档 → 08:00 摘要（KPI + 员工大会 + 三端截图）→ release_train bump → Vibe → Phase A/B/C → P2–P9 → 审批 → 部署 → 用户可见。  
> **当前代码状态**：Phase A/B/C 员工串联已落地；**默认 `MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE=shadow`**（只预览不真跑 git/部署）。

## 闭环阶段一览

| 阶段 | 时间 | 自动化状态 | 切 primary 后仍需人工 |
|------|------|------------|----------------------|
| 03:15 归档 | cron | ✅ 代码就绪 | 生产 cron 与 DB 持久化 |
| 08:00 摘要 | cron | ✅ 含三端截图段落 | Playwright + SMTP（见下） |
| 08:15 Phase A | cron | ✅ P-S Runner | Bench LLM / Tavily（岗位简报） |
| 08:25 Phase B/C | cron | ⚠️ shadow 默认 | 切 primary + GitHub + 审批 |
| installer/major 日 | 门禁 | ✅ 员工链已接 | COS 上传 + 签名 secret |
| 应用商店 | — | ❌ 未入日更链 | 软著 + 小米/华为开发者账号 |

---

## A. 您需在服务器 / 账号侧完成的断点（按优先级）

### A1 · 生产 MODstore `.env`（CVM `119.27.178.147`）

在 `/root/成都修茈科技有限公司/MODstore_deploy/.env`（或 systemd 引用的 env 文件）确认：

| 变量 | 建议值 | 说明 |
|------|--------|------|
| `MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE` | **`primary`** | 关闭 07:00 盲跑，08:25 真编排 |
| `MODSTORE_DAILY_ORCHESTRATOR_ENABLED` | `1` | 编排总开关 |
| `MODSTORE_RELEASE_TRAIN_ENABLED` | `1` | release_train SSOT |
| `MODSTORE_RELEASE_TRAIN_JSON` | 指向 `FHD/config/release_train.json` | 四段版本 |
| `MODSTORE_INBOX_POLL_ENABLED` | `1` | 邮件回信审批 |
| `MODSTORE_SMTP_*` | QQ 邮箱 + 授权码 | 发 08:00 摘要 |
| `MODSTORE_APPROVAL_AUTHORIZED_FROM` | 与 SMTP 发件一致 | 回信白名单 |
| `MODSTORE_EMPLOYEE_BENCH_PROVIDER` / `MODEL` | 如 xiaomi/deepseek | 员工大会 + Vibe |
| `MODSTORE_GITHUB_TOKEN` | `repo` 权限 PAT | auto/daily 分支 + PR |
| `MODSTORE_AUTO_PR_ENABLED` | `1` | 日更 PR |
| `MODSTORE_CR_GIT_AUTO_PR` | `1`（可选） | CR 自动开 PR |
| `MODSTORE_OPS_STAGED_AUTO_APPROVE` | `0` 起步 | 信任后改 `1` + 设 `AUTO_MAX_FILES` |
| `MODSTORE_REPO_ROOT` | 含 yuangon 的 git clone | 岗位简报锚定 |
| `MODSTORE_DAILY_SURFACE_AUDIT_ENABLED` | `1` | 三端截图 |
| `XCAGI_ANDROID_APP_FILING_APPROVED` | `1` | 备案展示 |
| `XCAGI_ICP_NUMBER` | 蜀ICP备… | 官网/App 一致 |

**人工操作**：编辑 `.env` → `systemctl restart modstore`（或 `./deploy.sh` 对应服务名）。

---

### A2 · Playwright（08:00 三端截图）

MODstore Python 进程所在机器需：

```bash
cd /root/成都修茈科技有限公司/MODstore_deploy
pip install playwright
playwright install chromium
# 无头 Linux 可能还需：
playwright install-deps chromium
```

验收：`python -c "from playwright.sync_api import sync_playwright; sync_playwright().start().chromium.launch().close()"`

若未安装，摘要邮件中会出现「未安装 playwright」而非 PNG。

---

### A3 · SSH / 部署凭据（本机 → CVM）

| 用途 | 配置位置 | 您需完成 |
|------|----------|----------|
| market 前端 | `market/.deploy-ssh.local` | `DEPLOY_SSH_KEY` 或 `DEPLOY_SSH_PASSWORD` |
| 营销静态站 `index.html` | 同上或 nginx 根目录 rsync | 上次 SCP **Permission denied** — 补密钥 |
| MODstore Python 代码 | git pull on CVM 或 CI | 确保 CVM clone 与 origin 同步 |
| release COS | `/root/.xcagi-cos.env` | `COS_SECRET_ID` / `COS_SECRET_KEY`（见 `setup-xcagi-cos-upload-on-cvm.sh`） |

market 推送（公网需显式允许）：

```bash
cd 成都修茈科技有限公司/MODstore_deploy/market
bash scripts/build-dist.sh
DEPLOY_ALLOW_PUBLIC=1 bash scripts/ssh-push-update.sh
```

---

### A4 · 邮件审批（每日必有人回信或开 auto-approve）

1. 08:00 左右收到摘要邮件，内含 **批准令牌**。
2. 用授权邮箱 **回复** 邮件正文含令牌 → `MODSTORE_INBOX_POLL_ENABLED=1` 轮询 IMAP 落盘。
3. 或在 QQ 邮箱开启 IMAP/SMTP 服务（设置 → 账户）。

**渐进信任**：低风险变更可设 `MODSTORE_OPS_STAGED_AUTO_APPROVE=1` + `MODSTORE_OPS_STAGED_AUTO_MAX_FILES=24`，仍建议保留邮件抄送观测。

---

### A5 · GitHub / gh CLI（日更分支 → PR → merge）

CVM 或编排宿主需：

- `git` 可 push `origin`
- `MODSTORE_GITHUB_TOKEN` 具备目标仓库 **contents + pull_requests**
- 可选：`gh` 已 `auth login`（`MODSTORE_CR_GIT_AUTO_PR=1` 时）

**人工**：在 GitHub 仓库 Settings → Actions 允许 workflow；Dependabot PR 合并策略与 branch protection 需与您期望一致（protected main 会挡 auto-merge）。

---

### A6 · 安装包 / 签名 / COS（installer 日 ×.×.N0.0）

| 平台 | Secret / 账号 | 文档 |
|------|---------------|------|
| Windows/macOS/Android 构建 | GitHub Actions secrets | `release-desktop.yml` |
| macOS 公证 | `APPLE_ID` / `APPLE_APP_SPECIFIC_PASSWORD` / 证书 | 可选，未配则 allow_unsigned |
| Android 签名 | keystore 在 CI secrets | `RELEASE_TWO_SKUS.md` |
| COS + CDN | 腾讯云 CAM + `dl.xiu-ci.com` 预热 | `deploy/docs/runbooks/xcagi-download-cdn.md` |

**人工**：installer 日后在 CDN 控制台对 `dl.xiu-ci.com` 做**缓存预热**（脚本输出会提示路径）。

---

### A7 · 应用商店（不在日更链内）

| 项 | 状态 | 您需完成 |
|----|------|----------|
| APP 备案 | ✅ 已通过 | 维持主体/包名三一致 |
| 软著 | ⏳ 材料在 `FHD/XCAGI/软著申请/` | [中国版权保护中心](https://www.ccopyright.com.cn) 提交 |
| 小米/华为等开发者 | ❌ | 注册开发者账号、上架素材、隐私 URL 可点击 |
| About 页备案链接 | ⚠️ | App 内备案号需可跳转 beian.miit.gov.cn（商店审核） |
| Firebase / 极光 | 可选 | `MOBILE_ANDROID_STORE_COMPLIANCE.md` |

官网 APK 分发 **`https://xiu-ci.com/market/download`** 不依赖商店，可并行。

---

### A8 · 可观测 / SRE（P1，不挡日更但挡「全闭环」）

- Grafana/Alertmanager/Loki **生产实例**导入 `FHD` 内 JSON 并配通知渠道（钉钉/邮件 webhook）。
- Blue-Green：`DEPLOY_BG_AUTO_PROMOTE` 生产未证。
- 全量 pytest 绿、覆盖率 90%：CI advisory，不阻塞 deploy。

---

## B. 代码侧已闭环（无需账号）

- Phase A `08:15` P-S Runner + 门禁
- Phase B `08:25` P-W/S-R WorkUnit + git 分支（primary）
- Phase C ProductionLine P3/P7/P8（日更）或 P3–P9（installer/major）
- `daily_digest_surface_audit.py` 九 URL 截图 + console 汇总 + **相对昨日 PNG hash Δ**
- `post_deploy_smoke.py`：部署后 `/health` + `https://xiu-ci.com/market/download`（`approval_dispatcher` 链）
- `vibe_prep_meta_json.orchestrator_audit`：`orchestrator_mode` / `shadow` 审计字段
- market 移动端 `/download`、工作台下载 Tab
- `release_train.json` 四段 SSOT
- Runbook：[ROLLBACK.md](./ROLLBACK.md) · [SLO_AUTO_MERGE_HALT.md](./SLO_AUTO_MERGE_HALT.md)

---

## C. 推荐切换顺序（降低风险）

1. **观测 3–5 天 shadow**：确认 08:00 邮件、截图目录、Phase B 日志无异常。
2. **配齐 A1–A3**（env + Playwright + SSH）。
3. **设 `MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE=primary`**，重启 MODstore。
4. **手动批准 1–2 次日更 PR**，验证 merge → deploy 路径。
5. **installer 日**前完成 A6 COS；**major 日**前核对 SKU/ADM。
6. 商店上架与 A7 并行，不阻塞官网 APK。

---

## D. 自检命令

本机（MODstore 根目录）：

```bash
bash scripts/verify_release_train_closure_env.sh
python -m pytest -m release_gate -q
```

生产（SSH 上）：

```bash
curl -sS http://127.0.0.1:8000/health | head
journalctl -u modstore -n 50 --no-pager | rg -i 'digest|release_train|orchestrator'
ls -la playwright-report/digest-surfaces/ 2>/dev/null | tail
```

---

## 相关计划

- **90 天对标大厂补齐**：[`FHD/docs/guides/RELEASE_GAP_CLOSURE_PLAN.md`](../../../../FHD/docs/guides/RELEASE_GAP_CLOSURE_PLAN.md)
- **代码补齐完成 handoff**：[`FHD/docs/guides/RELEASE_GAP_CLOSURE_COMPLETE.md`](../../../../FHD/docs/guides/RELEASE_GAP_CLOSURE_COMPLETE.md)
- **日更 PR staging 门禁**：[`FHD/docs/guides/STAGING_GATE_DAILY_PR.md`](../../../../FHD/docs/guides/STAGING_GATE_DAILY_PR.md)
- **post_deploy_smoke 定时任务**：`modstore_server/post_deploy_smoke_job.py`（`MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED=1`）

## E. 相关文件

| 文件 | 作用 |
|------|------|
| `modstore_server/daily_digest.py` | 08:00 摘要 |
| `modstore_server/daily_release_train_orchestrator_job.py` | 08:25 编排 |
| `modstore_server/digest_daily_line_chain.py` | Phase B/C |
| `XCAGI-Full-Pipeline.html` § 断点清单 | 可视化 gap |
| `.env.example` | 全量 env 注释 |
| `FHD/docs/guides/MOBILE_ANDROID_STORE_COMPLIANCE.md` | 商店合规 |
