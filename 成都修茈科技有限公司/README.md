# 成都修茈科技有限公司 — Monorepo

本仓库当前承载多个业务组件，正按照 [`docs/migration/split-repos.md`](docs/migration/split-repos.md)
拆分为多个独立仓库。在拆仓完成前，**本仓库使用"组件级 CI + 组件级部署"** 做边界隔离。

## 组件一览

| 组件                             | 路径                                                          | 语言/框架             | 独立 CI                                                            | 独立部署                                                               |
| -------------------------------- | ------------------------------------------------------------- | --------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| 营销官网静态页                   | `*.html`、`styles.css`、`main.js`、`assets/`、`site/`、`new/` | 原生 HTML/CSS/JS      | [`ci-marketing-site.yml`](.github/workflows/ci-marketing-site.yml) | —                                                                      |
| 根 Vue 3 项目（modstore-market） | `src/`、`package.json`、`vite.config.ts`                      | Vue 3 + Vite          | [`ci-root-frontend.yml`](.github/workflows/ci-root-frontend.yml)   | —                                                                      |
| MODstore market 前端             | `MODstore_deploy/market/`                                     | Vue 3 + Vite          | [`ci-market.yml`](.github/workflows/ci-market.yml)                 | [`market-live-deploy.yml`](.github/workflows/market-live-deploy.yml)   |
| MODstore Python 后端             | `MODstore_deploy/modstore_server/` 等                         | FastAPI / Python 3.11 | [`ci-backend-python.yml`](.github/workflows/ci-backend-python.yml) | [`deploy.yml`](.github/workflows/deploy.yml)                           |
| Java 支付子服务                  | `MODstore_deploy/java_payment_service/`                       | Spring Boot 17        | [`ci-payment-java.yml`](.github/workflows/ci-payment-java.yml)     | [`deploy-payment-java.yml`](.github/workflows/deploy-payment-java.yml) |
| vibe-coding 独立 Python 包       | `vibe-coding/`                                                | Python                | [`ci-vibe-coding.yml`](.github/workflows/ci-vibe-coding.yml)       | —                                                                      |

## 站点结构（营销站 vs Vue 应用）

本目录顶层存在**两条独立入口**，职责不同，勿混用：

1. **营销官网静态页（canonical，线上部署）**
   - 入口：根 [`index.html`](index.html)（多页站，另含 `about.html`/`contact.html`/`cases.html` 等）
   - 样式/脚本：根 [`styles.css`](styles.css) + [`main.js`](main.js)
   - 构建：静态页面配合下述证据资源重建；CI 见 `ci-marketing-site.yml`
   - 维护：修改静态页请直接改根 `*.html`/`styles.css`/`main.js`

2. **根 Vue 3 应用（modstore-market，独立产品）**
   - 入口：`src/main.ts` → `src/App.vue`，构建配置 [`vite.config.ts`](vite.config.ts)（dev 端口 5176，代理 `/api`→8765）
   - 构建：`npm install && npm run build`（产物在 `dist/`）；CI 见 `ci-root-frontend.yml`
   - 维护：改 Vue 应用请只动 `src/`，不要改根 `index.html`（那是静态营销站入口）

> 注意：根目录只有一份 `index.html`/`styles.css`，属营销站 canonical；Vue 应用通过 `vite.config.ts` 独立构建，二者互不覆盖。

## 工程原则

1. 每个组件有自己的 CI（独立 `concurrency` group + 路径过滤），改一处不会触发所有组件的构建。
2. 部署流水线按组件独立；不再默认依赖 monorepo 路径硬编码。
3. 跨语言全链发布脚本（`MODstore_deploy/scripts/remote_sync_extract.sh`、
   `_remote_deploy_extract.sh`）已标记 `[DEPRECATED]`，仅为未拆仓服务器过渡保留；
   新发布请使用 `python-release.sh` / `node-release.sh` / `java-release.sh`。
4. 运行期产物（outbox、webhook 投递 JSON、payment_orders、chroma）不进入源码仓库；
   由 `MODSTORE_RUNTIME_DIR` / `MODSTORE_WEBHOOK_EVENTS_DIR` 指向数据盘。
   提交门禁见 [`ci-runtime-artifacts-guard.yml`](.github/workflows/ci-runtime-artifacts-guard.yml)。

## 证据资源与发布副本

验收原件继续保存在 `FHD/docs/evidence/`；仅在官网留存的原件列于
`data/capabilities/evidence-materialization.json` 的 `retained_sources`。该清单逐件记录
原件路径、SHA-256、字节数以及兼容的公开文件名。`source_aliases` 将历史验收目录中
字节完全相同的媒体映射到一份现有原件；验收 JSON、路径声明和原始 SHA 保持不变。
`capabilities/assets/evidence/`
其余文件都是可重建副本，不再提交；文件存在不代表验收通过。

从本目录执行：

```bash
python3 scripts/evidence_assets.py check
python3 scripts/evidence_assets.py materialize
python3 scripts/build_capability_center.py --check
python3 scripts/build_public_site.py --check
```

重建先校验全部原件，再生成普通文件，保留原来的公开 URL、历史目录路径和字节内容。原件缺失或
哈希不符会在静态发布前终止。部署脚本、官网 CI 和本地构建均使用同一清单；新增
验收证据须先复核原件，运行 `build_capability_center.py` 更新清单和页面，提交原件、
清单及页面，不提交发布副本。CI 拒绝重新跟踪副本及新增字节完全相同的媒体。

需要迁移原件时，可在受控本地存储创建按内容去重的恢复包：

```bash
python3 scripts/evidence_assets.py archive --archive /approved/private/evidence.tar
python3 scripts/evidence_assets.py restore --archive /approved/private/evidence.tar
```

`archive` 不删除原件、不上传；恢复只接受当前仓库清单声明的路径和校验和，拒绝
覆盖不同内容。命令中的目录须由操作者指定已获授权的私有存储；目前没有配置或
宣称远端归档成功。历史报告引用、原始验收录像及其追溯信息在持久归档与取回验证
完成前继续保留。仅查看历史验收时可运行 `materialize-sources`，只恢复原目录媒体，
不生成官网副本。历史验收脚本的登记、哈希校验与交付总账读取入口亦支持此清单。
法律递交材料保留原目录布局，未纳入媒体合并。媒体发布策略不合格的历史记录仍按
原门禁阻断，不改写为通过。

产品界面和宣传资源的可重建副本使用根仓 `config/media-aliases.json`：员工图片、
共享品牌头像、徽标、官网优化图以及 App Store `live/` 副本均固定原图路径和哈希。
前端、商店 Vite 构建与官网部署会按组件生成普通文件；根 README 直接引用保留的
版本化 App Store 原图。手动恢复或只校验可在根仓运行：

```bash
node scripts/dev/materialize_media_assets.mjs --check
node scripts/dev/materialize_media_assets.mjs frontend
node scripts/dev/materialize_media_assets.mjs market
node scripts/dev/materialize_media_assets.mjs marketing
node scripts/dev/materialize_media_assets.mjs appstore
```

修改原图时同时复核清单中的 SHA-256 和字节数；不要提交生成别名。法律递交附件、
iOS 规定命名的图标及跨平台独立应用资源仍按其现有打包边界保留。

## 关键文档

- [仓库治理与多仓拆分计划](docs/migration/split-repos.md)
- [组件化发布契约](MODstore_deploy/docs/migrations/release-contracts.md)
- [CI workflow 约定](.github/workflows/README.md)
- [MODstore 架构](MODstore_deploy/docs/ARCHITECTURE.md)
- [MODstore 贡献指南](MODstore_deploy/CONTRIBUTING.md)

## 拆仓后的导航

当某个组件抽离到独立仓库后，本文件的对应行会改为指向新仓库 URL，
同时在本仓库保留一个 `<组件>/MIGRATED.md` 指路短文。
