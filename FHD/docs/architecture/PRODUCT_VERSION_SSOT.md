# PRODUCT_VERSION_SSOT

版本演进、发布意图和状态契约唯一目录：[`config/download_release.json`](../../config/download_release.json)。源码候选数字仍由 [`VERSION.md`](../../VERSION.md) 管理；不是公开发布声明。历史世代数从 `release_history` 去重生成，不能取版本尾号、GitHub 记录数或页面常量。

## 来源与边界

| 事实 | 唯一输入 / 派生视图 |
|---|---|
| 演进历史、说明、别名、发布意图 | `download_release.json`；`/data/release-history.json` 与产品线状态由此生成，独立于当前下载指针 |
| 源码候选、工具链映射 | `VERSION.md` → `version_sync.py` / `verify_version_anchors.py` |
| 制品身份与字节 | 原构建 `manifest.json` / `build-info.json`；以完整源码 SHA、build run、SHA-256 绑定，不按版本号猜 |
| 验收 / 晋级 | 原包验收证据及授权；手动清单、Windows interim 和各平台 OTA 分别核对 |
| 公开入口 | `/download-release.json` + 对应 manifest + Windows hotfix；必须读回，404/身份冲突即不可用，不能用历史说明兜底 |
| GitHub Releases | 标签发布流程的下游视图；draft/prerelease/别名不能当独立正式世代，也不能因缺 GitHub 条目否定官网历史 |
| 服务器部署 / 客户运行 | `ops/releases/*.json` 与 health / 安装回执；服务器 SHA 不得写成桌面制品 source_sha |

## 原包生命周期

`release_policy` 定义 `candidate → accepted → published → withdrawn`。每条历史可关联 `deliveries`，逐项包含 product、sku、platform、arch、channel、source_sha、build_run_id、artifact_sha256、signature、notarization、state 与 evidence；版本继承所属历史条目。不同架构/渠道不得合并状态。未知身份不填假值；未对账历史保留 `publication_state=unknown`，不能据此生成已发布数量。

1. **candidate**：从已合入 main 的准确 SHA 构建并冻结字节；源码改动、CI 通过或有安装包均不是发布。
2. **accepted**：同一原包完成声明范围的实机安装、升级、业务、数据保留及失败恢复，记录 `evidence.acceptance`。新 SHA / 重打包不能沿用旧证据。
3. **published**：再关联 `evidence.authorization/publication`，原字节晋级，读回 URL、大小、SHA-256、签名/公证、平台架构和更新元数据。未签名临时交付须有风险接受，禁止进入 stable OTA。
4. **withdrawn**：追加 `evidence.withdrawal`，保留发布与验收历史；撤回某渠道不抹除其他渠道事实。404 只是可用性异常，不能自动推断撤回。

历史 `.6` 手动交付验收成立，范围以原 `manual-download-manifest.json` 为准；它不代表后来同版本的新包、双架构或 OTA 已验收。历史 `.3` 下载说明与 CHANGELOG 发布声明处于不同时间点，制品待对账；`.4` 按 CHANGELOG 补入演进，不补造制品验收。官网历史记录数不等于正式稳定发布次数。前身项目只加入经仓库/制品证据确认的 provenance / aliases，不凭名称补造世代。

2026-10-26 只读核查：公开 `.6` 指针的 `manifest_url` 返回 404，Mac 首页入口关闭；历史手动包与当前 Windows interim 是不同制品。此运行问题仍 open，本次只补历史与治理，不修生产指针、不推进 OTA。

## 消费端接线现状（不是全部发布器已收敛）

| 消费端 | 实际生成 / 发布路径与当前缺口 |
|---|---|
| 官网历史 / 下载 | `product_lines_status.py::generated_views` 对目录复用公开脱敏策略；HTML 读 `/data/release-history.json`。下载仍核对既有指针与原包 manifest/hotfix，不以历史决定可用性。`generate-download-manifest.py::load_release_history` 已读取同目录。 |
| 发布说明 | 官网 notes 同源；`generate-update-metadata.mjs` 仍读 `XCAGI_RELEASE_NOTES` 或通用 fallback，CHANGELOG 是独立贡献记录/历史证据，尚未自动投影到 OTA。 |
| 客户端 OTA | `desktop-config.ts::SKU_UPDATE_URL` → `updater.ts` 读取 `latest[-mac].yml` 并验 Ed25519；metadata 生成器绑定 SHA/releaseId/包哈希，`release-desktop.yml` 校验跨平台与公开元数据。Mac OTA/fix-feed 晋级仍有独立入口。 |
| GitHub Release | `release-desktop.yml::github-release` 在 tag 与双平台/签名/下载中心门禁通过后上传同 manifest/pointer/assets；尚未配置同源 body，不能据此证明官网全部历史已登记 GitHub。 |

旧 market 下载页已由 `ca8bd212e` 迁出；本次退役无生产消费者的 `xcagiDownloadLinks` 静态猜 URL 工具、专属测试及构建参数/v8上传脚本，现役入口只使用经校验的官网数据。

当前 `deliveries` 校验是目录录入门禁，尚未强制所有桌面发布器消费它。后续须以同一纯生成器输出 OTA/GitHub notes，并让现有晋级入口共用逐制品验收门禁；不新增平行台账。服务器 fresh/reuse/activation/rollback 已增加当前公开指针字节与缺省集合校验，stale immutable 目标必须显式对账，不能偷偷改写；与并发桌面发布之间尚无共享锁，因此不能宣称完全消除 TOCTOU。

## 每次贡献与发布

- 修改版本、发布脚本、下载 UI、客户端更新或历史说明时，先核对本目录与原制品证据；只改源，重生成视图，不维护第二份版本表。仓库不保留旧公共指针副本；离线站点聚合只展示发布意图，不能代替线上读回。历史 kind / publication_state 是历史分类，不是当前平台可下载状态。
- 普通服务器/静态部署只能原字节保留已公开桌面指针；缺源则阻断/显示不可用，禁止用服务器 SHA、最大版本、mtime、候选目录或单平台 PASS 重建指针。
- 桌面授权发布先验收原包，再按 product/platform/arch/channel 晋级并读回各视图；GitHub 与官网不一致必须登记差异，不能任选一边覆盖历史。
- 执行 `python scripts/dev/ssot_cli.py check version product-lines`；后者校验历史身份/别名、逐制品身份与分状态证据、签名门禁及生成漂移。运行对应生成器/回归及 pre-push 门禁。无完整证据的发布保持 open，不能用文档通过代替客户交付。
