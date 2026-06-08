# xcagi-modstore · 仓库与分支规范（日更 AI 流程 SSOT）

> 目标：让「流程1（时间轨 · 日根线）」每天**可靠、可回滚、不爆分支**。全产品线 **v10 锁**，版本锚点恒 `10.0.0`。

## 仓库边界

| 仓库 | 角色 | 远端 |
|---|---|---|
| **xcagi-modstore**（本仓） | 姊妹栈 MODstore 部署源码 · 日更编排 + `cr_git_pipeline` 实际操作仓 | `github.com/42433422/xcagi-modstore`（private） |
| **FHD**（`../../FHD`） | XCAGI 主产品（后端/前端/桌面/移动/CI） | `github.com/42433422/ai-excel-helper` |
| 服务器 `/root/modstore-git` | 生产部署镜像 | 与本仓对齐 |

> 密钥零入库：`.env*` / `*.local` / `*.pem` / `*.key` / `_local_secrets/` 全部 `.gitignore`，只提交 `*.example` 模板。

## 分支模型（干净 · 不爆分支）

```
main                 ← 受保护，仅经 PR 合入；CI 绿 + 审批
└─ auto/daily        ← 长期日更集成分支（复用，不每天新建）
   ├─ cr/<id>        ← 单个变更请求短分支，合进 auto/daily 后即删（不逐个开 PR）
   └─ …
```

- **每天 1 个汇总 PR**：`auto/daily-YYYYMMDD`（从 `auto/daily` 切，或直接以 `auto/daily` 为 head）→ `main`；替代历史上「每个 CR 一个 PR」的爆炸式做法。
- **base 自动探测**：用 `origin/HEAD`（默认分支）解析，不硬编码 `main`。
- **同日幂等**：同一天重跑日更不重复建分支/PR（按 `day` 去重）。
- **自动清理**：合并/关闭后删 `cr/*` 与已合 `auto/daily-*`，保留窗口 7 天。
- **失败隔离**：git 步骤失败不阻断 digest 主链；`repo_root` 非 git 仓时干净跳过。

## 环境变量（日更 git 行为开关）

| 变量 | 默认 | 作用 |
|---|---|---|
| `MODSTORE_REPO_ROOT` | 本仓路径 | 日更 git 操作根（务必指向本 git 仓） |
| `MODSTORE_DAILY_BRANCH` | `auto/daily` | 长期日更集成分支名 |
| `MODSTORE_DEPLOY_PUSH_BRANCH_PREFIX` | `auto/daily-` | 每日汇总分支前缀 |
| `MODSTORE_AUTO_PR_BASE_BRANCH` | 自动探测 | PR base 分支 |
| `MODSTORE_CR_GIT_AUTO_PR` | `1` | CR 是否逐个开 PR（建议 `0`，走每日汇总 PR） |
| `MODSTORE_CR_BRANCH_PREFIX` | `cr` | CR 短分支前缀 |
| `MODSTORE_BRANCH_CLEANUP_KEEP_DAYS` | `7` | 自动清理保留天数 |
