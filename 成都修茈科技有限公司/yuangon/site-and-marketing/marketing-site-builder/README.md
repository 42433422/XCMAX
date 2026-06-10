# 营销站点构建员（marketing-site-builder）

## 一句话职责

负责 [`marketing-site/`](../../../marketing-site/) 独立营销站：Nunjucks 模板、`scripts/build.mjs`、npm 依赖与构建产物目录策略；与根目录 `site-content-editor` 负责的 Vite 静态站、`site/` 子目录明确分工。

## 负责路径

| 类型 | 路径 |
|------|------|
| 营销站根 | `marketing-site/**` |
| 典型入口 | `marketing-site/package.json`、`marketing-site/scripts/build.mjs` |

## 典型任务

1. 新增或调整 `templates/**/*.njk` 页面结构。
2. 升级构建脚本与依赖并验证 `npm run build`。
3. 与 SEO 员工对齐上线页元数据与站点地图引用。

## KPI

| 指标 | 目标 |
|------|------|
| 本地构建成功率 | 100% |
| 模板引用断裂（坏 partial） | 0 |

## 禁区

- `MODstore_deploy/**`
- `site/**`（归 `site-content-editor` / `retention-officer` 策略）
- `_local_secrets/**`

## 协作关系

- `site-content-editor`：根营销 HTML/Vite 内容边界对齐。
- `seo-sitemap-curator`：对外可见 URL 与 sitemap 同步。
- `deploy-release-officer`：若营销站纳入 CI/CD 管道时协同。
