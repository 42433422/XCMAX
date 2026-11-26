# CI SSOT（XCMAX 根仓）

**GitHub Actions 唯一调度入口**：[`.github/workflows/`](../.github/workflows/)

`FHD/.github/workflows/` 与 `MODstore_deploy/.github/workflows/` 保存实现源，**不会**被 GitHub 直接执行。修改后运行 `python scripts/dev/publish_ci_workflows_to_root.py`，以根目录生成副本调度；`--check` 校验两者一致。

## CI / PR 提速执行 SSOT（2026-09-28 立即生效）

> **适用对象**：Windows AI、Mac AI 及后续所有自动开发/修复 Agent。
> **目标**：缩短「发现问题 → 修改 → 验证 → 合并」的单轮时间，同时保留发布级质量门禁。
> 与本文档其他章节的关系：本节是**验证分级/PR 纪律的总纲**；required checks 清单见 [Branch protection（main）](#branch-protectionmain)，E2E 分层见 [E2E 分层](#e2e-分层)。

### 1. 总原则

禁止把每一次小修改都当成一次完整发布来验证。统一采用四级验证：

**本地快测 → PR 快速 CI → 夜间全量 CI → 发布前终极 Gate**

开发阶段优先追求快速反馈；全量验证集中执行。

### 2. PR 规则：一个问题只维护一个 PR

同一问题修复过程中：

- 可以连续提交多个 commit
- 可以继续修改同一分支
- 可以反复补测试
- **禁止因为发现第二层、第三层小问题就重新创建新的 PR**

只有以下情况才新开 PR：已进入另一个独立问题域、改动目标发生实质变化、原 PR 已经合并。

> 原则：**一个问题 = 一个 PR，而不是一次修改 = 一个 PR。**

### 3. 开发阶段：LOCAL FAST PATH

AI 每次完成代码修改后，默认只运行与改动直接相关的最小测试集。

| 改动类型 | 只运行 |
|----------|--------|
| 前端 | 对应 unit test、lint / type check、与修改页面直接相关的 smoke、必要时单条 Playwright 场景 |
| 后端 | 被修改模块对应单测、API contract / targeted integration tests、必要 lint / type check |
| 数据库迁移 | Alembic SSOT、migration validation、数据库相关 integration test（**仅改 migration / schema 时触发**） |
| macOS 专属 | **仅** macOS 构建 / runtime / 签名 / updater 等相关文件改动时，才跑 macOS 专属检查 |
| Windows 专属 | **仅** Windows 直接相关的 targeted test / 实机验证，不得自动牵连 macOS 完整流程 |

禁止默认运行：全量 E2E、全仓 backend tests、Alembic、Performance、Mutation、CodeQL、macOS runtime、mobile CI、Release Gate。不得因为改一个接口就运行整仓所有模块。

### 4. PR 阶段：FAST CI

普通 PR 的 CI 目标：**5–10 分钟内给出可合并反馈**。PR 只保留真正需要阻止明显错误进入 main 的检查。建议 Required Fast Checks：

- lint / syntax
- frontend-unit 或对应 backend targeted test
- Source Governance
- 必要 smoke test
- secrets / basic security guard
- 与 changed paths 直接对应的专项检查

所有工作流必须优先使用 **changed paths / path filter / change detection**，不相关模块直接 skip（屏蔽示例见 [`fhd-test.yml`](../.github/workflows/fhd-test.yml) 的 path 过滤）。

### 5. 禁止普通 PR 默认全跑的任务

以下检查原则上移出普通 PR 快路径，统一进入 **Nightly / Release Gate**：

- 全量 E2E
- Release gate CI
- Performance Smoke Test
- mutation-smoke
- 全量 CodeQL
- 全量 gitleaks 深扫
- Mac control runtime contract
- 跨平台完整 smoke
- mobile Flutter / iOS 完整 CI
- 全模块 MODstore test
- 全量 archive / artifact 深度检查
- 大型 benchmark
- 完整 release provenance
- 安装包发布验证

### 6. 夜间 CI

每天夜间针对当天最新 `main` 运行一次完整验证，至少包含：

- 全量 backend tests / 全量 frontend tests
- E2E / Smoke Tests
- Performance / Mutation
- CodeQL / gitleaks
- Alembic / migration
- Runtime Artifacts Guard
- Mac runtime contract / Windows / macOS 关键契约
- mobile CI
- Release Gate
- 必要 benchmark

夜间 CI 允许耗时较长。**开发 Agent 不得等待夜间 CI 完成才继续第二天之前的普通开发任务。**

### 7. Nightly 失败处理

| 等级 | 示例 | 处理 |
|------|------|------|
| **P0 / P1** | 登录失效、数据丢失、安装失败、权限绕过、安全问题、主流程完全不可用 | **立即阻止发布，并创建修复任务** |
| **P2 / P3** | 边缘 UI、非主流程测试、性能轻微退化、非阻断性 warning | 记录问题并继续开发，**不得让整个仓库停下来反复跑 CI** |

### 8. 发布前 Gate

只有准备：出正式安装包 / OTA / 客户交付 / stable release / production deployment，才执行真正完整的发布门禁。必须包括：

**完整 CI + Windows 实机 + Mac 实机 + 安装 / 升级 / 登录 / 绑定 / 运行真实证据。**

发布级 Gate 不能被 Nightly 替代（实机验收口径见 `FHD/docs/MACOS_RELEASE_SSOT.md`、`FHD/docs/WINDOWS_RELEASE_SSOT.md`）。

### 9. 当前 XCMAX 特别要求

禁止出现「改 3 个前端文件 → 全仓十几套 CI 全部重新执行」。正确行为应为：

**前端权限修改 → frontend unit → targeted smoke / e2e → governance / security 基础检查 → 合并**

其余完整检查交由夜间 CI。

### 10. AI 执行纪律

Windows AI / Mac AI 在开始任何修改前，都必须先判断：

1. 修改属于哪个 subsystem？
2. 最小需要验证哪些测试？
3. 哪些 CI 与本次改动无关？
4. 当前是否可以继续使用已有 PR？
5. 是否真的属于发布级操作？

如果答案不是「正在发布」，不得自行升级成完整 Release Gate。

### 11. 禁止行为

- 每改一次代码就跑全仓
- 每发现一个小问题就新开一个 PR
- 无关平台 CI 跟随运行
- 为等待 CI 停止后续独立开发
- 为了「保险」无条件运行全部测试
- 已有成功结果没有代码影响却重复执行
- Nightly 能完成的验证强制塞进每个 PR
- 把「测试越多」错误理解为「质量越高」

> 质量目标：**正确的测试，在正确的时间运行。**

### 12. 推荐流程

```text
发现问题
  ↓
定位 subsystem
  ↓
修改代码
  ↓
本地 targeted test
  ↓
继续修改同一个 PR
  ↓
PR Fast CI
  ↓
合并 main
  ↓
继续下一个问题
  ↓
夜间统一 Full CI
  ↓
发现异常再生成修复任务
  ↓
真正发布前跑 Full Release Gate
```

### 13. 例外申请

任何 Agent 若认为必须恢复全量 PR CI，必须明确写出：

1. 哪一个具体风险要求这样做
2. 哪一条测试只有全量流程能够发现
3. 为什么 Nightly / Release Gate 无法承担

否则默认继续执行本 SSOT。普通 bug fix 的目标为「修改 → 快测 → PR 验证 → 合并」尽量在分钟级完成，开发速度以**有效修复数量 / 单位时间**衡量，而非「跑了多少次 CI」。

## 分片执行与耗时观测（2026-11-22）

保留现有 11 个 required checks、测试全集及覆盖率基线，调整工作流依赖与报告成本。`guard-temp-scripts` 在同一次检出中完成临时文件守卫、统一分类和分片计划，质量检查与分片只等待这一任务；`SSOT Drift Gate` 同时运行，`backend-test`、`frontend-test` 最终聚合仍显式要求守卫与 SSOT 均成功。聚合使用 `always()`，分类失败、质量失败、分片缺失或取消不能变成成功。

| 环节 | 执行与验证口径 |
| --- | --- |
| 事件去重 | Flutter、Android smoke、Market E2E 和 Retort 的分支 push 限定 main/develop/master，特性分支由 PR 验证；保留 tag、手动及既有定时入口。源 workflow 与根镜像的触发路径分别保留，生成器仅重写精确的根路径。 |
| 旧轮取消 | 无副作用的 PR 测试和守卫按 workflow/PR 分组取消旧轮；非 PR 以 run_id 隔离。可信主线的 `cancel-superseded-ci.yml` 在同仓 PR synchronize 后只读元数据：新 head 冲突等原因未触发原生取消时，对同 PR、同主 CI、旧 head 的原始 attempt 请求官方普通 cancel；只有同 attempt 已有 cancelled job 且仍未完成时才使用 force-cancel 收尾。取消前复查事件 head、live PR、run/attempt、时间边界和完整 jobs，身份缺失或漂移即停止；没有取消证据的人工重跑不启动清理。它不检出 PR 内容，也不修改检查结论；当前 head 的 `always()` 聚合仍失败阻断。发布、部署及缓存预热沿用各自策略。Mac 专项分类精确补取 base/head 后读取 diff，缺失时仍保守全跑。 |
| 统一分类 | `change_classifier.py --all` 只读一次 diff；绑定实际 checkout SHA。PR 使用 merge SHA；base/head 只负责分类。diff 缺失或为空时全跑。 |
| 后端分片 | 默认 32 片，最多同时 64 片；手动 `backend_shards` 可选 4/8/16/24/32/48/64。导入前按当前 pytest 配置枚举文件、按历史模块耗时分配，各片只收集自己的文件。汇总从同版源码独立重算文件全集与分配，逐文件核对收集回执、用例和执行结果，保留 run/attempt/source 与文件哈希校验。 |
| 后端安装 | uv 使用同一 Python 安装现有 requirements，并从同一 uv.lock 同时固定 pytest、pytest-cov、coverage；锁缺失或歧义时在安装前停止。缓存绑定 requirements、uv.lock 及本地包声明，安装后校验依赖一致性，每片保存解析版本。其余间接依赖仍以实际清单和回归为准。 |
| 后端报告 | stdlib 先验证所有证据及工具链，再只安装分片实际使用的 coverage 版本。full/behavior 数据隔离生成 JSON，保留 XML 和两道 ratchet；HTML 仅手动 `--html`。逐阶段耗时保存在 `backend-aggregate-timings.json`。 |
| 前端分片 | 全集只运行 8 片 Vitest，合并原生 blob/V8 和 JUnit 后执行原全局阈值及 `--require-frontend`。验证完整文件集合、片号唯一、身份及原始报告哈希。源码与测试 ESLint、stub/any 棘轮及现有 advisory vue-tsc 在质量任务执行。 |
| 下游验证 | mock E2E 与打包提前开始；容器扫描等待实际打包产物。镜像发布仍等待前后端聚合、E2E、安全、容器扫描、打包和架构检查。 |
| 无关变更 | 只有守卫和 SSOT 均成功、有效分类、正确源码、质量任务成功且分片明确 skipped 时，聚合才接受 skip；空输出或未知状态均失败。 |

原 `Vitest (173 文件 · jsdom)` 与 `frontend-smoke` 检查名称保留为轻量兼容任务，显式要求 `frontend-test` 聚合成功；上游失败、取消或跳过均拒绝。兼容任务和镜像结果转接任务使用 `!cancelled()`，在整次工作流被取消时释放旧 PR 并发槽；两道必需的前后端聚合门禁仍使用 `always()` 核对证据，取消不会产生成功。`frontend-smoke` 还运行原仓库卫生检查。独立重复 Vitest、smoke 子集和 mock E2E 已移除；真实全栈 E2E、严格构建、安全扫描及覆盖率门禁保留。当前 `coverage_ramp` 为零时，后端复用已验证的 full 结果作为 behavior 结果，不重复执行测试。

独立 `Smoke Tests` 将仓库卫生检查合并为 `backend-smoke` 安装前的第一道检查，保留失败阻断，减少一次串行排队与检出。Smoke 和真实 API E2E 复用官方 setup-uv 下载缓存及当前源码安装校验。离线 Agent 评测的可选 `--junitxml` 保留原退出码和公开摘要，只保存用例 ID、类型、失败检查名及 SHA/run/attempt；fixture 内容与凭证不进入报告，开始执行前删除同路径旧报告。`always()` 上传用于诊断，缺失报告不能将失败改成成功。

构建复用须同时匹配源码、构建配置及 run/attempt。现有服务器打包产物继续供同轮下游使用；真实 API E2E 将随机 API 端口编入前端，因此不能复用其他配置的 dist。测试结果、整套虚拟环境及不同身份的报告不作为下载缓存复用。

测试去重须核对实现、输入、夹具和独有断言，保留有效场景；不以文件名或执行条数判断质量。现有 `test_bloat_report.py --check` 同时拒绝后端测试的字面 `assert True` 和同一状态码集合同时接受成功与服务器错误。业务回归应核对精确状态、响应及副作用；ELT 全栈闭环验证预演不写入、未确认拒绝、执行后读回及重复提交拒绝，模型闭环使用真实会话与适配器、仅替代外部 HTTP 传输，不调用付费模型。

### 比较时间的方法

计时范围是同一提交全部 required checks 完成，并包含排队与环境准备。若没有真实事件接收时间，使用最早 workflow `created_at` 作代理起点并标注；不得把一次手动主工作流结果当成全部 11 项的耗时。PR head、被测试的 merge source、base、各 workflow run/attempt 分别保留。

从 `FHD/` 运行离线分析：

```bash
python scripts/ci/measure_required_checks.py snapshot.json --output report.json
```

`snapshot.json` 包含 `repository`、`head_sha`、`event`，PR 额外提供 `pull_request_number`、`base_sha`；`required` 是分支 API 的 `protection.required_status_checks`（含 App 绑定），`runs` 为各 run 原始对象，`checks` 为完整 check-runs 响应，`jobs` 为各 run 完整 jobs 响应。分页须收齐，可传完整分页数组。可选 `observed_at`、`cache_state`；只有真实调用方记录才填写 `triggered_at` 与 `trigger_kind`。

工具按 check ID 与 job/run 身份关联，拒绝跨 SHA、旧 attempt、重复、缺页或错误 App 的替代结果。证据不完整会输出报告并退出 1，不把未知状态算作成功；报告不是合并授权或测试源码证明。合并后 GitHub 可能清空 run 的 PR 关联，旧样本只能保留 observed 耗时，不能补造关联。

历史样本 [PR #2494](https://github.com/42433422/XCMAX/pull/2494) 的 11 项观察完成时间为 **23 分 30 秒**，仅作单样本参照。新的提速幅度和“三分钟”目标以本分支真实 PR 结果验证，不由分片数推算成已达成。比较时同时记录冷/热缓存与 runner 分钟，避免用更多计算量掩盖排队。

本次变更涉及分片选集及覆盖率汇总，PR 需完成一次实际全集验证，确认模块隔离、文件全集及合并覆盖率等价；仅跑小 fixture 无法发现全部模块的顺序依赖，留到合并后的 Nightly 会让有风险的门禁先进入 main。该验证针对共享 CI 改造，不扩大普通业务修复的默认范围。

## 仓库 git 历史说明（2026-08-01）

本仓当前工作区的 git 历史**始于 2026-07-21**（首个 commit `1b6ae8560`，`fix(deploy): bootstrap FHD staging on single CVM`）。
该日期之前的提交历史不在当前本地克隆中；远程仓库 `github.com/42433422/XCMAX` 的
旧分支/标签与 GitHub 侧 PR/Actions 记录仍是历史追溯的补充渠道。
对早于 2026-07-21 的变更归因，请查 GitHub 远程历史而非本地 `git log`。

## 分层

| 层级 | 路径 | 说明 |
|------|------|------|
| **仓根 SSOT** | `.github/workflows/*.yml` | push/PR/schedule 在此触发 |
| **FHD 实现源** | `FHD/.github/workflows/*.yml` | 编辑后运行 `python scripts/dev/publish_ci_workflows_to_root.py` 同步到根 |
| **MODstore 实现源** | `成都修茈科技有限公司/MODstore_deploy/.github/workflows/*.yml` | 同上 |

> **生成 vs 手写**：根仓 `fhd-*.yml` / `modstore-*.yml` 由 publish 脚本从实现源生成，文件头为
> `# CI SSOT: generated from … — DO NOT edit here`。**请改实现源后重跑 publish**，勿直接改根副本。
> 以下根仓 workflow 为手写（无生成头，直接在根仓维护）：
> `corp-site-deploy.yml`、`desktop-macos-smoke.yml`、
> `e2e.yml`、`e2e-playwright-reusable.yml`。

## 常用 workflow

| 用途 | 根 workflow |
|------|-------------|
| FHD 后端 + 前端 + Docker | [`fhd-ci-cd.yml`](../.github/workflows/fhd-ci-cd.yml) |
| FHD 轻量 smoke（path 过滤） | [`fhd-test.yml`](../.github/workflows/fhd-test.yml) |
| FHD Release gate | [`fhd-release-gate-ci.yml`](../.github/workflows/fhd-release-gate-ci.yml) |
| 前端 Vitest | [`fhd-ci-cd.yml`](../.github/workflows/fhd-ci-cd.yml) → `frontend-test-shard` / `frontend-test` |
| Playwright 全栈 | [`e2e.yml`](../.github/workflows/e2e.yml) → [`e2e-playwright-reusable.yml`](../.github/workflows/e2e-playwright-reusable.yml) |
| 浏览器工具执行契约（path 过滤） | [`fhd-browser-runtime.yml`](../.github/workflows/fhd-browser-runtime.yml)，真实 Chromium 必跑、禁止 skip |
| Flutter Android+iOS CI | [`fhd-ci-mobile-flutter.yml`](../.github/workflows/fhd-ci-mobile-flutter.yml) |
| Flutter Android 发布 | [`fhd-release-android.yml`](../.github/workflows/fhd-release-android.yml) |
| Flutter iOS / TestFlight 发布 | [`fhd-release-ios.yml`](../.github/workflows/fhd-release-ios.yml) |
| MODstore Python CI | [`modstore-ci-backend-python.yml`](../.github/workflows/modstore-ci-backend-python.yml) |
| FHD 服务器 API 发布包校验 | [`fhd-ci-cd.yml`](../.github/workflows/fhd-ci-cd.yml) → job `pack-verify` |
| FHD 全产品线 tag 编排 | [`fhd-release-orchestrator.yml`](../.github/workflows/fhd-release-orchestrator.yml) |
| FHD 单机 CVM 手动 rolling | [`fhd-deploy.yml`](../.github/workflows/fhd-deploy.yml) |

## 稳定版发布 tag 约定

- **产品版本锚点**：产品 `1.0.0.1`，工具链 `1.0.0`（见 `FHD/VERSION.md`）。
- **Git tag（发版触发）**：`FHD/v1.0.0.1`；制品身份同时记录 `git_sha` + `sha256`。
- **串联（单一编排入口）**：`FHD/v*` tag 仅触发两个 workflow —— `fhd-ci-cd.yml`（测试+镜像+CVM）与 `fhd-release-orchestrator.yml`。后者先跑 `verify-version-anchors`，再 **dispatch** 客户端 `fhd-release-desktop/web/android.yml`（**仅 Android**；服务器由 `fhd-ci-cd` 的 `cvm-push-release` 负责）。这些被编排的 workflow **已移除自身 `FHD/v*` tag 触发**，避免 tag 推送时双重运行。桌面验收见 [双端平级 SSOT](../FHD/docs/desktop_platform_parity_ssot.md)，服务端按已登记的部署链执行。

## 多环境 channel（stable / staging）

| Channel | 远端 manifest 目录 | 用途 |
|---------|-------------------|------|
| `stable`（默认） | `/var/www/update/releases/stable/server/` | 生产 compose（5100） |
| `staging` | `/var/www/update/releases/staging/server/` | 预发 / dry-run（建议 5101 + 独立 `FHD_DEPLOY_ROOT`） |

**打包 / 推送**（`FHD/` 根目录）：

```bash
# 生产
bash scripts/deploy/fhd-pack-release.sh
bash scripts/deploy/fhd-push-release.sh

# 预发 channel
FHD_RELEASE_CHANNEL=staging bash scripts/deploy/fhd-pack-release.sh
FHD_RELEASE_CHANNEL=staging bash scripts/deploy/fhd-push-release.sh
```

manifest 含 `"channel": "stable"|"staging"`。同一台 CVM（119.27.178.147）可并存两目录。

**Staging 首次引导（CVM root）**：

```bash
bash /opt/fhd-full/scripts/deploy/fhd-bootstrap-staging-cvm.sh
# 或仓库副本: bash FHD/scripts/deploy/fhd-bootstrap-staging-cvm.sh
```

会创建 `/root/fhd-staging.env`、`/opt/fhd-staging`、`fhd-staging.service:5101`、
nginx 路径 `https://xiu-ci.com/fhd-staging-api/`，以及 staging manifest。
`staging.xiu-ci.com` 需另配 DNS A → `119.27.178.147`（可选；workflow 已用 path health）。

staging cron 示例：

```bash
FHD_MANIFEST_PATH=/var/www/update/releases/staging/server/fhd-manifest.json \
FHD_DEPLOY_ROOT=/opt/fhd-staging \
FHD_SERVICE_NAME=fhd-staging.service \
FHD_HEALTH_PORT=5101 \
FHD_ENV_FILE=/root/fhd-staging.env \
FHD_AUTO_UPDATE_LOCK=/tmp/fhd-staging-auto-update.lock \
bash /opt/fhd-staging/scripts/deploy/fhd-auto-update.sh
```

## CVM 制品上传（GitHub Actions 手动触发）

`fhd-ci-cd.yml` job **`cvm-push-release`**：仅在 `workflow_dispatch` 明确设置 `push_to_cvm=true` 且 `docker-build-fhd-api` 成功后上传制品。服务器上传采用严格模式，缺少目标或 SSH 配置即失败。stable 上传绑定同一 main SHA 的原安全证据，并设置 `FHD_PUSH_APPLY_NOW=0` 等待部署审批；staging 可立即应用。

手动触发：`Actions → CI/CD Pipeline → Run workflow` → 勾选 **Push release artifacts to CVM**，选 channel；所需 `FHD_PUSH_*` 配置统一见下方 Secrets / Variables 清单。

**仍需人工（仓外）**：GHCR `read:packages` PAT 写入服务器、`/root/fhd-full.env`、首次 cron 安装、branch protection。

## 单机 CVM 手动 rolling（`fhd-deploy.yml`）

生产唯一路径：单台腾讯云 CVM（`119.27.178.147`）上的 **tarball + docker compose**。
制品上传见上文 `cvm-push-release`；stable 的应用由 `fhd-deploy.yml` 原审批链核验发布身份后执行。

`fhd-deploy.yml` 使用所选 GitHub Environment，通过 SSH 执行 `apply-latest` 或 `restart-only`；环境审批要求以对应配置为准。生产应用必须提供完整 `release_sha` 与 `release:<同一 SHA>` action ID，经过原发布审批并核对 stable manifest；应用后核对部署标记及健康接口中的实际 SHA。

> 2026-07-14：已删除 `FHD/k8s/`、`FHD/helm/` 及 blue-green/canary/GitOps/预览环境等从未接通真实集群的清单与文档路径。
> 历史脚本已外置归档（见根 `ARCHIVE_POINTER.md` 第六批 `docs-20260917-batch6/`）；需要时从归档或 git 历史取回。


## Secrets / Variables 清单

**Settings → Secrets and variables → Actions**（Secrets 与 Variables 两页）。标「跳过」者缺失时对应步骤跳过（不致 CI 失败）。

| 名称 | 类型 | 用途 | 缺失行为 |
|------|------|------|---------|
| `GITHUB_TOKEN` | 自动 | GHCR 推送、`gh workflow run` dispatch、GitHub Release | 自动注入 |
| `FHD_PUSH_HOST` | Secret / Var | CVM 推送目标 | Actions 服务器上传失败；桌面按对应工作流处理 |
| `FHD_PUSH_SSH_KEY` | Secret | CVM SSH 私钥（**勿入库**） | Actions 服务器上传失败 |
| `FHD_PUSH_USER` | Secret | CVM SSH 用户（默认 `root`） | 用默认 |
| `SERVER_SSH_KEY` | Secret | 桌面安装包上传 SSH 私钥（缺失则回退 `FHD_PUSH_SSH_KEY`） | 桌面上传跳过 |
| `CODECOV_TOKEN` | Secret | 覆盖率上传 | 步骤 `continue-on-error` |
| `APPLE_ID` / `APPLE_APP_SPECIFIC_PASSWORD` / `APPLE_TEAM_ID` | Secret | macOS 公证 / 签名 | 出未公证包 |
| `CSC_LINK` / `CSC_KEY_PASSWORD` | Secret | **macOS Developer ID Application** `.p12`（base64 或路径）+ 导出密码；`fhd-release-desktop` 导入钥匙串签名，**不再**用 API 现场签发（Account Holder 限制） | 缺则 macOS job 失败 |
| `STAGING_BASE_URL` | Var | 容量 k6 目标（`fhd-capacity-staging-monthly`） | 容量测试跳过 |
| `STAGING_PROMETHEUS_URL` | Var / Secret | SLO 采集 Prometheus 端点 | SLO 采集降级 |
| `XCMAX_GIT_BRANCH` / `XCMAX_REMOTE_ROOT` | Var | 企业站 `corp-site-deploy` 同步参数 | 用默认 |
| `COSIGN_VERIFY_DISABLE` | Var | 置 `1` 临时跳过部署前 `cosign verify`（break-glass） | 不设=强制验证 |

> Phase 1（供应链）起 cosign **keyless**（Sigstore + GitHub OIDC）签名**免私钥**，不新增长期密钥。生产部署不依赖 kubeconfig。

## 生产 SLO 采样链

`fhd-slo-metrics-collect.yml` 在采集前核对既有 `automation/slo-metrics-` 发布记录：未合并的采样 PR、最新记录关闭但未合并、来源不明或当前检出未包含上一份合并提交时停止。作业串行执行不能替代证据已合入主线，后续采集与发布不得越过该检查。

采集器与验证器共用原始证据链校验。只有全部历史记录都属于未绑定版本的 `preflight`、原始摘要有效且全部可从创世记录到达时，才允许对历史分叉建立一次审计 epoch；首条新记录绑定每份历史原始文件的摘要、分叉点和末端，历史文件保持原样。历史缺失、改写、正式记录分叉或新 epoch 再分叉继续阻断。旧预检不计入正式观察天数；正式 Day 0 仍须线上版本收敛，持续天数、同一 release、指标样本、时效和采样覆盖继续按原发布门禁验收。

## 桌面三架构长时运行

手动 `fhd-desktop-soak.yml` 使用 `main` 的验收控制代码，分别在已登记的 Windows x64、macOS arm64、macOS x64 三台专用交互桌面执行安装版。输入的完整 `release_sha` 必须已在 main，`product_version` 必须在既有版本目录；预装应用的 build-info、后端运行 SHA、窗口版本和实测文件摘要必须一致。Windows/macOS 账号使用各自的专用测试身份，普通 PR 不在有凭据的 self-hosted 设备上执行。

设备需有 `self-hosted`、对应 OS、对应 `X64` / `ARM64` 架构、`xcagi-physical` 标签及可用的交互桌面；标签由维护者按设备登记赋予，本身不是物理硬件的加密证明。仓库变量 `XCAGI_SOAK_WINDOWS_BINARY`、`XCAGI_SOAK_MACOS_ARM64_BINARY`、`XCAGI_SOAK_MACOS_X64_BINARY` 分别指向实际可执行文件。对应 secrets 为 `XCAGI_SOAK_WINDOWS_USER` / `XCAGI_SOAK_WINDOWS_PASS` 和 `XCAGI_SOAK_MACOS_USER` / `XCAGI_SOAK_MACOS_PASS`。采集器还核对机器架构、原始 PE / Mach-O 包头及 macOS 原生执行状态，不能以 Rosetta 翻译执行替代 Intel 原生验收。缺设备、安装包或凭据时保留阻断，不能用托管虚拟机或 Linux 短测替代。

唯一采集入口为 `FHD/scripts/release/desktop_soak.py`；旧 `desktop-soak.sh` 已移除。脚本使用独立临时 userData 和回环端口，真实登录后交替打开设置、聊天、客户、产品页，持续至少 28,800 秒。稳定性策略统一在 `verify_desktop_soak.py`：采样缺口最多 90 秒，整棵进程树 RSS 最多 2 GiB、稳定窗口增长最多 256 MiB，句柄/文件描述符最多 16,384、增长最多 512，按主机逻辑 CPU 归一化的平均利用率最多 80%，95% 以上持续超过 180 秒阻断。这是当前桌面验收预算，不是实际测得结果或全部部署方式的容量承诺。

长跑后实际执行渲染网络离线恢复、渲染进程崩溃恢复、后端崩溃恢复、桌面正常重启、附加窗口创建/关闭、正常退出；故障仅作用于本次启动的进程与隔离数据。正常退出必须留下本进程的干净退出标记且没有残留进程；失败清理无法确认完成时保留私有测试目录。主进程、后端、GUI、资源和版本任何必要观测缺失均不能通过。此流程覆盖桌面生命周期与界面活性；真实模型业务、系统睡眠唤醒和安装升级回滚仍使用各自的原始验收证据。

每轮和每个故障阶段保存原始 JSON，取消或失败也上传；渲染崩溃和未处理页面错误即时落盘，采样间隙发生后自行恢复也不能漏报，错误内容仅保留摘要。三架构原始文件 `windows.json`、`macos-arm64.json`、`macos-x64.json` 聚合为 `xcagi-desktop-soak`，旧双平台报告仍保留，但缺少第三架构时不能取得完整资格。独立验证器从原始样本重算时长、资源、页面覆盖和故障结果；缺架构、短测、重复 PID 身份、静态窗口、非预期崩溃、伪 `passed` 字段及缺失证据均被拒绝。`--measurements-only` 的成功退出仅表示测量格式和内容合格，不能认证设备来源。

既有 `closure-evidence-report` 使用 `desktop_soak_run_id`，由 `build_closure_reports.py collect` 核对原始工作流、当前 attempt、main 祖先、原始制品摘要以及三个不同的登记 runner 作业，再将报告字节摘要绑定到可靠性报告。缺少任一架构长跑证据时，原生产可靠性报告继续阻断；既有 SLO、安装升级回滚、安全与客户验收条件同时保留。原生 runtime-contract 矩阵执行采集器和验证器回归，这些短测不产生八小时实机资格。

## 超大源码增长审查

800 行仍是提醒线，不是文件长度硬上限。沿用 `scripts/dev/source_governance.py`
的全栈生产源码范围及测试/生成目录排除。PR 从真实 merge-base 到 head 的净行数
增加，且最终超过 800 行时（含新增或首次越线），required `arch-fitness` 检查
`scripts/dev/source_growth_review.py`。存量不增长、缩短、纯重命名不触发；从测试或
未治理目录移入生产范围按新增处理。等行重写及用删行抵消新增不由本门禁判定质量。

审查请求的唯一登记文件是 `config/source_growth_reviews.json`。先提交源码，再运行
`python scripts/dev/source_growth_review.py --base origin/main --head HEAD --print-template`，
将对应条目合入登记文件，补全后提交。每个路径绑定本次前后 blob、前后行数及原路径；
新增文件的 base_file/base_blob 为 null。继续修改源码后必须重新核对这些值，不能用
刷新 source_governance_baseline、提高总行数基线或借旧请求消除本次增长记录。

每条请求填写：reason（为什么增加）、boundary（为什么仍属同一职责，或后续可按什么
业务边界拆分）、validation（测试命令、结果与尚未验证部分）、follow_up（负责人及
后续动作，确无拆分计划时写理由）、review_owner（GitHub @用户或 @组织/团队）。
字段不能留空或仅放占位词。只校验本 PR 增长文件，历史请求不阻塞无关变更；
不设置周期续期要求。后续增长仍须匹配对应的前后内容；相同变更记录不代表新 PR 已经获批。

评审者应在 PR 中逐项确认这些说明、职责内聚与测试证据，拒绝只为凑行数的
part/mixin 分片、动态 facade 回调和同职责搬家。PR 正文列出触发文件与净增量，
标注审查待完成；review_owner 是请求负责人，不是已获批准的证明。CI 只验证记录的
完整性和精确变更绑定，不认证审批、说明真实性或架构质量；GitHub 的实际评审和
既有保护流程仍必须执行。本次不改 branch protection，不自动 approve/合并。
既有路由数、重复源码、机械分片以及 FHD 已登记文件增长棘轮保持独立阻断；本登记
不豁免它们。必要的既有基线调整仍须说明并经评审，不能删除无关代码凑净删除。

## Branch protection（main）

> 合入顺序与**快车道**（小修复类 PR 可优先于主序列合入的条件、判定权与合入后流程）以仓根 [AGENTS.md](../AGENTS.md#合入顺序与快车道2026-10-19-0337-用户定) 为准；快车道不豁免下列 required checks。

GitHub 实配 11 项 required status checks（2026-10-21 API 复核）：`guard-temp-scripts`、`arch-fitness`、`security-scan`、`gitleaks`、`analyze (python)`、`analyze (javascript-typescript)`、`SSOT Drift Gate`、`Release gate (hard block)`、`backend-test`、`frontend-test`、`mutation-smoke`。本轮不调整此清单或 App 绑定。

`arch-fitness` 的源码增长登记绑定当次实际检出的 PR merge SHA：先确认 checkout 等于 `github.sha`、提交恰有两个父节点且第二父节点等于事件 head，再以第一父节点和 head 的 merge-base 比较。事件 base SHA 仅留作诊断，不用已过期的事件基点或会移动的 `origin/main` 代替被测合并；身份或历史缺失仍阻断。登记继续读取精确 head 的已提交目录，不表示架构评审已批准。

`backend-quality` 的 mypy/lint 失败由 `backend-test` 汇总阻断；`frontend-quality` 的 ESLint/any 棘轮失败由 `frontend-test` 汇总阻断。普通 CI 的 vue-tsc 保持 advisory；发布验证中的严格构建仍按原流程执行。后端同时检查 full 和 behavior 两个口径；前端在合并原生覆盖率后执行全局阈值与 ratchet。数值以 `FHD/metrics/coverage_ratchet_baseline.json` 及测试配置为准，不在此复制历史地板值。本地发布验证入口为 `bash FHD/scripts/dev/release_verify.sh`。

**文档新鲜度门禁**（2026-09-09 起，`arch-fitness` job 内硬阻断，check 名仍为 `arch-fitness`）：`docs_ssot_lint.py --strict`（SSOT 声明与登记表一致）、`verify_doc_versions.py`（docs 版本表述对齐 `VERSION.md` 锚点）、`verify_doc_claims.py`（文档覆盖率数字必须源于 SSOT 快照）、`gen_claimed_vs_actual.py --check`（`CLAIMED_VS_ACTUAL.md` 与 `metrics/` 一致；日更 metrics 由 `fhd-slo-metrics-collect.yml` 同步重生成该文档）。

> **Public 仓库**：`42433422/XCMAX` 已为 **PUBLIC**；Actions 对 public repo 有免费额度。若 job 仍报 `payments have failed or spending limit`，在 [Payment information](https://github.com/settings/billing/payment_information) 添加有效支付方式。

> **Actions 账单**：若所有 job 在数秒内失败且 annotation 为 `recent account payments have failed or your spending limit needs to be increased`，须在 **Settings → Billing & plans** 修复付款或提高 spending limit；此阻断与 workflow/代码无关。

## FHD 生产服务器部署 runbook（tarball 拉取式）

**原则**：生产机 `/opt/fhd-full` **只跑制品、不 git pull、不手改代码**；配置在 `/root/fhd-full.env`（不入库）。

| 步骤 | 命令（在 `FHD/` 根目录） |
|------|--------------------------|
| 1. 锚点校验 | `python3 scripts/dev/verify_version_anchors.py` |
| 2. 打包 | `bash scripts/deploy/fhd-pack-release.sh` |
| 3. 推送到 update 站 | `bash scripts/deploy/fhd-push-release.sh`（需 SSH key 到 `119.27.178.147`） |
| 4. 服务器 cron 应用 | 每 5 分钟 `fhd-auto-update.sh` 读 manifest → `fhd-apply-release.sh` |
| 5. 首次/切换 cron | 服务器：`bash /opt/fhd-full/scripts/deploy/fhd-install-server-cron.sh` |

**健康检查**：`curl -sf http://127.0.0.1:5100/api/health`（服务器）或经 Nginx `https://xiu-ci.com/fhd-api/api/health`。

**若新制品启动失败**：临时冻结 manifest 防止 cron 反复重试：  
`mv /var/www/update/releases/stable/server/fhd-manifest.json{,.hold}`

**回滚**：`fhd-apply-release.sh` 健康检查失败会自动从备份目录回滚；也可手动：

```bash
FHD_RELEASE_TARBALL=/opt/fhd-full/.deploy-last.tar.gz bash /opt/fhd-full/scripts/deploy/fhd-apply-release.sh
```

**产物路径**：`/var/www/update/releases/stable/server/fhd-manifest.json` + `fhd-full-*.tar.gz`。

**manifest v1 字段**：`artifact`、`sha256`、`git_sha`、`deploy_mode: "tarball"`。

## FHD 生产服务器部署 runbook（compose 镜像 · Phase 2）

**原则**：与 tarball **双模共存**；manifest `deploy_mode` 决定 cron 路由。镜像身份用 digest 钉扎，产品版本保持 `1.0.0.1`。

| 步骤 | 命令 / 说明 |
|------|-------------|
| 1. CI 构建镜像 | `fhd-ci-cd.yml` job `docker-build-fhd-api`：`docker/Dockerfile.fhd-api` → `ghcr.io/<org>/<repo>/xcagi-fhd-api:sha-<git_sha>` |
| 2. manifest v2 | 同次流水线合并 `image` + `image_digest`（`fhd-merge-manifest-image.sh`）；仍含 tarball 字段 |
| 3. 本机推送 | `bash scripts/deploy/fhd-push-release.sh`（manifest + tarball 原子 scp 到 update 站） |
| 4. 服务器 GHCR 登录 | **一次性**：`echo $GITHUB_PAT | docker login ghcr.io -u <github_user> --password-stdin`（PAT 需 **`read:packages`**；`gh auth token` 默认不含此 scope，pull 会 `denied`） |
| 4b. 无 PAT 时引导 | CI artifact / update 站 `fhd-api-image.tar.gz` → `bash scripts/deploy/fhd-load-release-image.sh`（`fhd-apply-release-compose.sh` 在 pull 失败时会自动尝试） |
| 5. compose 文件 | 首次 tarball 应用后位于 `/opt/fhd-full/docker/docker-compose.fhd-prod.yml` |
| 6. cron 路由 | `fhd-auto-update.sh`：`deploy_mode=image` → `fhd-apply-release-compose.sh` |
| 7. 健康检查 | `curl -sf http://127.0.0.1:5100/api/health`（与 tarball 相同；容器内 5000，宿主机 5100） |

**manifest v2 额外字段**：

```json
{
  "deploy_mode": "tarball",
  "image": "ghcr.io/42433422/XCMAX/xcagi-fhd-api",
  "image_digest": "sha256:..."
}
```

切换至 compose：将远端 manifest 的 `deploy_mode` 改为 `"image"`（或服务器设 `FHD_DEPLOY_MODE=image`），并确保 Docker + ghcr 登录就绪。

**手动 compose 应用**：

```bash
FHD_API_IMAGE=ghcr.io/42433422/XCMAX/xcagi-fhd-api \
FHD_API_IMAGE_DIGEST=sha256:<from-manifest> \
bash /opt/fhd-full/scripts/deploy/fhd-apply-release-compose.sh
```

**compose 回滚**：健康检查失败自动回滚至 `.deploy-image-digest` 上一值；也可手动指定旧 digest 再执行 apply-compose。

**生产切换 checklist（需 SSH，勿在 CI 自动执行）**：

1. 确认 `docker compose version` 与 `docker login ghcr.io` 成功  
2. `systemctl stop fhd-full.service && systemctl disable fhd-full.service`（避免与 5100 端口冲突）  
3. 确认 `/root/fhd-full.env` 中 `DATABASE_URL`、`SECRET_KEY`、`CACHE_REDIS_URL`（可用外部 Redis，无需 `--profile bundled-redis`）  
4. 数据卷：`/opt/fhd-full/data`、`uploads`、`logs`、`mods` 已由 compose 挂载  
5. 将 manifest `deploy_mode` 改为 `image`，或导出 `FHD_DEPLOY_MODE=image` 于 cron 环境  
6. 手动跑一次 `fhd-apply-release-compose.sh` 验证，再依赖 cron  

**冻结错误制品**（两种模式通用，**手动运维操作**，CI 不自动执行）：`mv .../fhd-manifest.json{,.hold}`；cron 见 manifest 缺失即跳过，不会反复重试坏制品。

## Python 格式化 / lint（FHD）

| 工具 | CI 状态 |
|------|---------|
| **Ruff** | `fhd-ci-cd.yml` / `fhd-test.yml` — 唯一 formatter + linter（`ruff check` + `ruff format --check`） |
| **black / isort** | **禁用** — 与 Ruff 冲突；CI、本地 pre-commit、FHD dev 依赖均不得重新启用 |

`guard-temp-scripts` 使用 `FHD/scripts/ci/guard_temp_scripts.py`：对 `_find_zero.py` / `_analyze_coverage.py` 做全量 tracked 扫描，对新增 `_fail*.txt`、`*.v1_backup`、根级/直挂 `scripts/` 的 `fix_` / `check_` / `final_` / `recover_` / `debug_` / `test_` 临时脚本做增量拦截（合法后端单元测试位于 `FHD/tests/`，不受影响）。本地 pre-commit 同步执行同一脚本。

## 安全扫描门禁策略（FHD）

| 扫描 | Job / 工具 | 策略 |
|------|-----------|------|
| 容器漏洞 | `container-scan`（Trivy，`severity: CRITICAL,HIGH`，`exit-code 1`） | **硬门禁**：决策矩阵"安全扫描 CRITICAL → 阻断"指此项 |
| 依赖 CVE | `security-scan`（safety `--full-report`） | **Advisory**（非阻断）：输出 `::warning::`，需人工 triage |
| 静态代码（广） | `security-scan`（bandit `-lll --skip B101,B601,B110 --exit-zero`） | **Advisory** |
| 静态代码（SQL 注入） | `security-scan`（bandit `-lll -s B608`，无 `--exit-zero`） | **硬门禁** |

全量安全扫描的定时任务只作趋势检查，历史风险 baseline 仅在此模式使用，制品命名为 `xcagi-security-trend-*`。
手动发布扫描直接运行部署端同一个 `verify_security_scan_pair.py`，核对同 SHA、扫描器完整性、新鲜度、同 UTC 日及零适用高危；保留 `xcagi-security-release-*` 制品名称，趋势制品不能作为发布准入。

发布消费者同时传入仓库与原始扫描 run ID，复用 `verify_modstore_release_approval` 回读成功的主线手动扫描、当前 attempt、原始 artifact 元数据及归档摘要，再逐文件比较下载内容。读取期间 attempt 变化、旧尝试制品、错误工作流、跨仓来源或扫描报告结构异常均阻断。扫描生产者在上传前可做本地自检；本地自检结果本身不能代替消费者的来源核验。

正式 orchestrator 复用 `measure_required_checks.py --repository … --release-sha …` 读取当前 main 的完整 App 绑定规则、checks 和最新 workflow/jobs。保留真实事件及 run/attempt，拒绝同名工作流歧义、非成功的最新尝试和读取期间身份变化；历史 commit status 不能覆盖失败的 required check。该结果仅证明检查身份与状态，实际测试源码、安装包及生产读回由各自原有门禁核对。

macOS 冻结双架构修复保留原发布开关和精确 SHA 授权：由主线控制器传 `--authorized-frozen-sha`，核对该 SHA 是当前 main 祖先，并执行相同的完整检查。门禁代码从控制器提交独立检出；原安装包、产品源及版本仍来自已授权的冻结提交。该参数携带原授权身份，不授予发布权限，也不适用于普通 orchestrator。

冻结桌面、稳定制品上传、生产 apply 与 Windows hotfix 同样从触发工作流的主线 `github.sha` 独立检出校验器，并核对实际控制器提交；产品构建和原包仍绑定 `release_sha`，因此旧产品提交无需具备新版校验 CLI。正式桌面流程只允许当前 run/attempt 读取本次已完成作业的原制品，并核对调用工作流、控制器 SHA 和 `release_sha → controller → main` 祖先关系，不能沿用其他进行中的运行。Windows 临时下载指针分别核对原安装包、交付回执和摘要旁文件，任一不符均在发布前失败。

> 把 safety / bandit-broad 设为 advisory 是有意为之（传递依赖 CVE 常需评估、不宜直接红）；真正的供应链信任在 **Phase 1** 由 SBOM + cosign 签名 + SLSA provenance + 部署前 `cosign verify` 补强。

## 供应链信任（Phase 1 · SBOM + 签名 + Provenance）

`fhd-ci-cd.yml` → job `docker-build-fhd-api` 在推送 `xcagi-fhd-api`（按 digest）后：

| 步骤 | 工具 | 产物 |
|------|------|------|
| 镜像签名 | cosign **keyless**（Sigstore + GitHub OIDC，`id-token: write`，**无私钥**） | GHCR `.sig` |
| SBOM | `anchore/sbom-action`（syft，SPDX-JSON） | `fhd-api-sbom` artifact + cosign attest 附着 |
| Provenance | `actions/attest-build-provenance`（SLSA，`push-to-registry`） | GHCR attestation |

**部署门禁**：`fhd-deploy.yml` 两个环境在 `kubectl apply` 前 `cosign verify`（keyless，校验 OIDC issuer + 本仓 workflow 身份）；验证失败 **拒绝部署**。

- 身份正则：`^https://github.com/<org>/<repo>/.github/workflows/.+@refs/(heads/main|tags/FHD/v.+)$`
- **Break-glass**：设仓库变量 `COSIGN_VERIFY_DISABLE=1` 临时跳过验证（仅紧急；恢复后清除）。
- 制品身份仍为 `git_sha` + `sha256` + cosign digest，产品版本保持 `1.0.0.1`。

## Codecov（FHD 后端）

`fhd-ci-cd.yml` → job `backend-test` 上传 `coverage.xml` 至 Codecov。**可选**：需在 GitHub **Settings → Secrets → Actions** 配置 `CODECOV_TOKEN`；无 token 时步骤 `continue-on-error`（不阻断 CI）。本地 `coverage.xml` / `htmlcov/` 仍为 SSOT。

**覆盖率门槛 SSOT**：唯一真值 = `FHD/pyproject.toml` → `[tool.coverage.report] fail_under`（当前 `78`，对应 `source=[app]` 真实行为口径行覆盖 floor——2026-09-01 D2-5：`coverage_ramp` stub 82 个清零迁出后总口径=行为口径，floor 自 78 行 / 69 分支起步只升不降，决策记录见 `FHD/docs/adr/0005-coverage-floor-recalibrate-stub-retirement.md`；历史宣称 88/81 含 stub 注水已废止）。分支 floor（69）与前端 floor 见 `FHD/metrics/coverage_ratchet_baseline.json`；对外现状口径见 `FHD/metrics/coverage-dual-summary.json`。

**后端覆盖率门禁唯一硬 gate = 行为口径（Delta A，2026-08-05；2026-09-01 D2-5 起与总口径合一）**：`backend-test` 的 `Behavior coverage gate` 步骤用 `coverage_ratchet.py --check --behavior --require-backend --record` 做硬阻断，floor 见 `coverage_ratchet_baseline.json` 的 `behavior_floors {lines, branches}`（78/69）。历史机制为排除 `coverage_ramp` 注水 stub（`-m 'not coverage_ramp'`）；2026-09-01 stub 82 个已全部去前缀迁出为契约测试（行为口径真实实测 79.26% 行 / 70.87% 分支为 2026-07-25 快照；清零后迁出用例计入行为口径），`tests/conftest.py` 打标逻辑与 marker 保留防复活（`count_coverage_ramp_stubs.py --check` 基线 0）。全量 `coverage.json` + `fail_under`（现 78/69）与行为口径数值一致，不再是独立宣称口径。`backend-test` **不再**用 CLI `--cov-fail-under` 硬编码阈值；标准命令传 `--cov-fail-under=0`。

`FHD/scripts/ci/check_coverage_ssot.py` 在 smoke/full CI 中校验上述三个文件互相一致，并禁止 `pyproject.toml` 复制动态 pytest passed/failed 快照；动态实测只允许出现在 `coverage-dual-summary.json`。

## E2E 分层

| 场景 | Workflow | 模式 | 用例 |
|------|----------|------|------|
| FHD 全量 CI（PR） | `fhd-ci-cd.yml` → `frontend-e2e` | `E2E_VITE_MOCK_API=1` + Vite :5001 | `npm run test:e2e:p0` → **8 pass / 6 skip** |
| 前端/后端 path 过滤、nightly、手动 | `e2e.yml` → `e2e-playwright-reusable.yml` | 每次运行均为 `E2E_FULL_STACK=1`，含严格构建和真实 FastAPI | 全栈 P0 与 `plan2026-skeleton`，结果以当次报告为准 |
| 浏览器执行器、Agent 工具入口、契约、测试或依赖变化 | `fhd-browser-runtime.yml` | `XCMAX_BROWSER_REQUIRE_REAL=1`，固定 Playwright 依赖与 Chromium，保持 sandbox 开启 | runtime/snapshot：真实表单回执、下载、隔离、域名策略、快照隐私、iframe 遮罩、生产资源限制、超时及租约；Agent 整链：真实审批、spawn、归属文件和幂等回读。两份独立 JUnit 缺失、skip 或失败均阻断该 job |

浏览器专项源位于 `FHD/.github/workflows/browser-runtime.yml`；先只安装 `pyproject.toml` 的 browser extra 与 `uv.lock` 中的 pytest、pytest-asyncio、SQLAlchemy、PyYAML、psutil、Pillow，以 `--confcutdir=tests/test_infrastructure` 执行 runtime/snapshot。随后按 `requirements-server-api.txt` 和既有部署锁约束安装服务器依赖，以 `--confcutdir=tests/test_application` 单独执行 `test_browser_agent_e2e.py`，保留原 AgentToolExecutor 与真实子进程浏览器。每轮保存提交、run/attempt、Python/Playwright 版本、服务器锁摘要及实际依赖版本、两份 JUnit 和合成页面产物。本地 skip 不构成验收；专项成功须由对应提交的实际运行确认，不改变既有分支保护清单。

SSOT 脚本：`FHD/frontend/package.json` → `test:e2e:p0`；编排见 `FHD/scripts/dev/e2e-full.sh`。

本地 `make e2e` 支持 Linux/macOS，使用每轮随机凭据、临时数据库与私有浏览器 profile；始终核对自有回环监听与市场 guard，失败或中断先停止本轮服务，使会话失效，再清理私有产物。Linux 使用子 reaper 确定性回收孤儿后代；macOS 按进程身份尽力回收已观察后代，父进程瞬间退出时未观察到的 detached 浏览器可能残留，不宣称同等资源回收保证。`runtime-contract` 的 `macos-15` 针对性验证通过后才可确认实际 Darwin 兼容性，Linux 伪平台分支测试不能替代。

## 同步根 workflow

```bash
# 改 FHD 或 MODstore 下 workflow 后，重新发布到根
python scripts/dev/publish_ci_workflows_to_root.py
git add .github/workflows/
git commit -m "ci: sync root workflows from FHD and MODstore_deploy sources"
```

根 workflow 文件头含 `# CI SSOT: generated from ...` 注释，标识生成来源。

## 克隆与提交

```bash
git clone https://github.com/42433422/XCMAX.git
cd XCMAX
# commit / push 均在仓根
```

历史子仓 remote（`ai-excel-helper`、`XCMAX-roadmap`、`xcagi-modstore`）已退役；旧 `.git` 备份见 `~/XCMAX-archives/nested-git-backup-20260608/`。


## 分支生命周期策略（branch lifecycle）

仓库历史上积累了大量远端/本地分支（886 / 193），部分 `behind main` 达 121–517，
合并冲突成本爆炸。遵循以下策略控制分支增量，并配套安全清理工具。

> **2026-08-05 受控清理已完成**：远端分支 **888 → 324**（删除 564 个，含 32 个已合并
> `devfleet/*sub-1*` + 530 个未合并 devfleet agent 分支，另 2 个运行中新生成）。`prune_stale_branches.py`
> 默认 dry-run 报告曾显示 `active=862 / stale=6 / deletable=0`（因 2026-07-21 git 历史重置，
> 所有分支提交时间均在旧阈值内，安全口径下无可自动删除项）。真正的僵尸来源是 **562 个
> 未合并自动 agent 分支**（`devfleet/cursor` + `codex` + `trae` + `claude_code`），它们领先
> `main` 巨大（ahead 1389+）且从未合并；本次按人工逐个审查后删除（保留当时 6 个开放 PR
> 分支，其 PR 随清理一并关闭）。**事后约定**：devfleet 子任务分支为一次性 agent 快照，
> 任务完成后由编排器自行清理，不再沉淀为长期分支。

### 命名规范
- 特性分支：`feature/<module>-<short-desc>`（如 `feature/admin-orders-foundation-ui`）
- 修复分支：`fix/<short-desc>`（如 `fix/lane-payload-loop`）
- 热修分支：`hotfix/<short-desc>`（如 `hotfix/cvm-autonomy-watcher-incident`）
- 发布分支：`release/<version>`（**受保护，永不删除**）
- 自动化/工具分支：`auto/`、`codex/`、`devfleet/`、`trae/`、`backup/`、`recover/`、`split/`、`merge/` 等
- 长期主线：`main`、`develop`（**受保护，永不删除**）

### 合并即删
- 合并进 `main` 的功能/修复分支，合并完成后原则上立即删除远端+本地分支。
- 有开放 PR 的分支**永不删除**（防止误删进行中的工作）。

### 陈旧阈值
- 默认：超过 **30 天无提交** 即视为 `stale`。
- `deletable` = 已合并进 `main` + 超过陈旧阈值无提交 + `behind main` 超过阈值。
- 人工清理时可按需放宽（`--stale-days` / `--before` / `--behind`）。

### 清理工具（安全 dry-run 优先）
`FHD/scripts/dev/prune_stale_branches.py` 默认 **dry-run 只输出分类报告**，
仅 `--apply` 才真正 `git push origin --delete`。分类：`active` / `stale` /
`deletable` / `protected`。保护清单（main / develop / release/* / 当前分支 /
开放 PR 分支）永不删除。

```bash
cd FHD
.venv/bin/python scripts/dev/prune_stale_branches.py            # dry-run 报告
.venv/bin/python scripts/dev/prune_stale_branches.py --list-all # 全量清单（dry-run）
.venv/bin/python scripts/dev/prune_stale_branches.py --apply    # 真正删除可删远端分支
.venv/bin/python scripts/dev/prune_stale_branches.py --apply --prune-local  # 追加清本地
.venv/bin/python scripts/dev/prune_stale_branches.py --before 2026-06-01 --behind 50 --stale-days 60
```

> **安全护栏**：删除前务必先跑 dry-run 核对报告；`--apply` 是不可逆操作，建议
> 分阶段（先 `--before` 框定范围）执行。


## 单机部署速查（替代已删除的 K8s/Helm 节）

```bash
# 自动：main/tag → fhd-ci-cd → cvm-push-release → 服务器 fhd-auto-update.sh
# 手动 break-glass：
gh workflow run fhd-deploy.yml -f environment=production -f action=apply-latest
# 或仅重启 compose：
gh workflow run fhd-deploy.yml -f environment=production -f action=restart-only
```

健康检查：

```bash
curl -sf https://xiu-ci.com/fhd-api/api/health
```

## 自治闭环（Autonomy）

> **详细手册**：[autonomy.md](./autonomy.md)
> **范围**：桌面 / 服务器 / CI 三端一体化自治系统，覆盖用户三大痛点 — 触发闭环 / 非代码故障 / 副作用预测。

### 三端自治链路

| 端 | 实现 | 触发方式 | 主要职责 |
|---|---|---|---|
| 桌面 | `FHD/desktop/autonomy/controller.ts` | main.ts start() + backend exit ingest | backend 崩溃回滚 / 降级状态修复 / OTA 失败回滚 |
| 服务器 | `FHD/scripts/autonomy/cvm_autonomy_watcher.py` | GitHub Actions cron `*/10 * * * *` SSH 触发 | health_down / manifest_drift / disk_full / compose_unhealthy |
| CI | `FHD/scripts/ci/ai_self_heal.py` + `ai_review.py` | `workflow_run(failure)` + `pull_request(opened/synchronize)` | CI 失败自愈 + PR 自动 review |

### CI Workflows

| Workflow | 触发 | 文件 |
|---|---|---|
| `fhd-ai-self-heal.yml` | 失败运行 + 每小时 17/47 分已有事故对账 + 手动只读盘点 | `.github/workflows/fhd-ai-self-heal.yml` |
| `fhd-ai-review.yml` | `pull_request` opened/synchronize | `.github/workflows/fhd-ai-review.yml` |
| `fhd-ai-self-heal-auto-merge.yml` | 北京时间每天 02:00–05:00 串行集成已排定的主线 PR，持续核对已合入 PR 的主干 CI 回执 | `.github/workflows/fhd-ai-self-heal-auto-merge.yml` |
| `fhd-para-nightly-release.yml` | GitHub Actions 每天北京时间 06:00 核对合入回执，提交待审核的版本候选 PR | `.github/workflows/fhd-para-nightly-release.yml` |
| `fhd-para-github-worker.yml` | 原派工 → 独立执行/发布/续验/验收 job | `.github/workflows/fhd-para-github-worker.yml` |
| `fhd-cvm-autonomy-watcher.yml` | `schedule(*/10 * * * *)` + workflow_dispatch | `.github/workflows/fhd-cvm-autonomy-watcher.yml` |

Para 在窗口内可唤起既有 GitHub Actions 工作流。工作流按 `XCMAX_MAIN_MERGE_QUEUE`
中的次序处理 `main` 的 PR。仓库维护者在所需评审完成后，按终极员工已确认的顺序登记 JSON 数组，
每项包含 `pr` 和完整 `head_sha`。空数组等同于本轮没有待合入 PR。首个未合入的 PR 如有
`hold-merge`、检查未通过或提交变化，后续 PR 等待该项处理。分支落后于 `main` 时，发起
GitHub 分支同步，评审和 CI 核对新提交后更新队列中的 `head_sha`，再继续集成。
GitHub 上未解除的评审修改要求会暂停合入。源码增长评审在登记该提交前完成。
每次请求合入前复核当前时刻，05:00 起仅处理已有回执及原 SLA 事项。

02:00–05:00 盘点北京时间昨天创建、当前目标为 `main` 的全部 PR，包括队列外与已关闭的
PR。合入仍使用既定顺序和 GitHub 保护规则。06:00 仅由批准队列中的 PR 阻断候选准备，
并逐个核对批准的提交及其合入回执属于 `main`；队列外与已关闭的未批准 PR 只作盘点。
本轮有新增合入且队列已收口时，预检后生成带 `hold-merge` 的候选版本 PR。维护者审核并
登记该精确提交的顺序后才可合入，随后沿既有正式发布流程构建和验收。该工作流的手动触发供只读核对。
全域 OTA 晋级以 Para 复测、各渠道签名与发布回执为输入。

### 关键约束

| 约束 | 说明 |
|---|---|
| 稳定身份与恢复 | 工作流以 API 路径/ID 归一；源码事件只观察已有事故，由串行对账任务恢复，20/5 创建预算不阻止可信原任务续接。关闭事故不永久屏蔽同提交的新失败；查询不足不关单。 |
| `autonomy/` 分支不递归 | ai-self-heal 不处理 `autonomy/*` 分支失败，避免自愈自愈递归 |
| 执行与发布隔离 | 模型 job 不接收发布凭据；独立 publisher 核对原派工、官方 artifact SHA-256、Git 祖先与精确分支，不 checkout/执行候选；原共享身份入口仍硬拒绝。 |
| 合并与发布状态 | 同一 head 的独立审核和完整检查通过，merge API 仍校验 SHA；持久 PR 回执恢复部分派发。未知派发结果持续对账，72 小时未确认转人工；只有明确拒绝才有限重试，已观测 run 不重派。主干 CI 成功不代表部署成功。 |
| 交付完成 | Retort 分支验收后沿原 LangGraph checkpoint 等待受保护合入、同 SHA CI/安全扫描、正式发布回执与线上制品身份，才写入已交付知识；历史仅分支验收记录不追认为上线成功。 |
| `confirmed-high` 才阻断 | ai-review 仅 LLM 高置信度（confirmed-high）高危问题才阻断合并 |
| 跨端门禁默认禁用 | env `XCAGI_CROSS_TIER_GATE=1` 启用，fail-open（查询失败不阻断） |
| ImpactPredictor 拦截不阻断 | 误判仅写 audit，不抛错；deny 时不执行但记录原因 |
| Policy 纯函数 | 禁止 `Date.now()`，时间窗口用 signals 自身 `ts`（取最新信号 ts 作为"现在"） |
| 所有动作必审计 | AuditEntry 是唯一事后真相，三端共用语义；通过 `audit_query.py` CLI 查询 |

从 `FHD/` 执行 `python scripts/ci/ai_self_heal.py --reconcile --dry-run` 仅生成 `test_reports/self_heal_reconciliation.json`；省略 `--dry-run` 才按证据续接或处理已替代事故。手动工作流设置 `reconcile=true` 默认只读，定时对账自动恢复。超过文件体量、授权缺失或不明写入结果仍明确等待处理，不通过提高阈值回避。GitHub 发布凭据按 VM 隔离；执行器仍使用现有 Para 设备及管理服务身份，不宣称模型与同一执行 VM 的管理进程相互隔离。现有 `run_attempt=1` 保护继续有效，失败 GitHub 工作空间需按原派工核对，不保证任意 workflow 重跑都能续接。

原 PR 和客户反馈修复仅接受已有 `srt-0.0.83-header-only-platform-v1` 隔离及原请求的已批准预算：可信控制器持有模型凭据，模型进程只获得占位符，实际调用经过原逐调用额度预留与结算。原 PR 使用自身 MacControlTask、原请求摘要及派生预算身份，不能借用客户工单或 Retort 身份。缺少批准、隔离或可信用量时继续等待；环境白名单、工作区权限、提示词约束与秘密扫描均不能代替这些条件。

独立 publisher 核对原 attempt、原候选和不可变隔离证据；即使远端候选分支已存在，也须验证原证据才能签发发布回执。原 Issue 消费者在全新 bare Git 仓库中只读取对象，验证祖先关系和受限改动，持久化唯一更新意图，并重新核对原 Issue/PR 与实时发布授权，再以原 head 为期望值执行 CAS 快进。候选树与 hooks 不执行，`main` 不在此写入范围内。丢失确认后只读原 PR HEAD/CI，候选发布或 CI 被观察到都不等于修复完成；只有原候选同提交的真实 CI 终态才结算原任务，正式合入与生产发布继续走原保护和审批。

### 触发条件矩阵

| 信号源 | 触发动作 | 自动/人工 |
|---|---|---|
| 桌面 backend 5min 内 ≥3 次 exit | `rollback_version`（high） | 自动决策 + CrossTierGate 预检 + 人工 escalate 兜底 |
| 桌面 disk_full | `clear_cache`（low） | 自动执行 |
| 桌面 disk_low / db_corrupt / network_down | `escalate`（high） | 直接人工 |
| 桌面 ota_install_failed | `rollback_version`（high） | 自动决策 + 预检 |
| 服务器 /api/health 持续 503 | `restart_service`（max_attempts=2） | 自动 + 失败 escalate |
| 服务器 manifest_drift | `freeze_manifest` | 自动（防 cron 反复重试） |
| 服务器 disk_full | `clear_logs` | 自动 |
| 服务器 compose_unhealthy | `restart_service` | 自动 |
| CI fhd-ci-cd 失败 | 创建修复 PR + 标 `needs-human` | 自动诊断 + 人工合并 |
| PR opened/synchronize | ai-review 行级评论 | 自动（confirmed-high 才阻断） |

### 跨端门禁场景

| 场景 | 检查项 | 防止问题 |
|---|---|---|
| 桌面 `rollback_version` | `server_manifest_frozen` | 桌面回滚到服务器已冻结的版本 |
| 服务器 `rollback_to_last_tarball` | `desktop_pending_rollback_marker` | 嵌套回滚导致数据丢失 |
| CI `cvm-push-release` | `server_manifest_frozen` | CI 推送覆盖运维手动冻结的 manifest |

### Audit 查询

```bash
# 查桌面端最近 24h 的所有 rollback 动作
python scripts/autonomy/audit_query.py --source desktop --since 24h \
  --filter 'action.type=rollback_version'

# 查服务器端最近 1h 失败的动作
python scripts/autonomy/audit_query.py --source server --since 1h \
  --filter 'result.ok=false'
```

完整用法与运维剧本见 [autonomy.md](./autonomy.md)。
