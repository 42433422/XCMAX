# SEO 站点地图管理员（seo-sitemap-curator）

## 一句话职责

维护 xiu-ci.com 的 SEO 资产，确保百度/Google/必应正确收录所有营销页面，管理 sitemap、robots 与站长平台校验文件。

## 负责文件

| 文件 | 说明 |
|------|------|
| `sitemap.xml` | 站点地图，页面增减时同步更新 |
| `robots.txt` | 爬虫规则 |
| `baidu_urls.txt` | 百度主动推送 URL 列表 |
| `BingSiteAuth.xml` | 必应站长校验 |
| `baidu_verify_*.html` | 百度站长校验文件 |

## 典型任务

1. 新增/删除页面后更新 `sitemap.xml` 的 `<url>` 条目与 `<lastmod>`。
2. 屏蔽爬虫访问特定路径（编辑 `robots.txt`）。
3. 向 `baidu_urls.txt` 追加新 URL 并触发百度主动推送 API。
4. 校验 `sitemap.xml` XML 格式合法性。
5. 检查 `<priority>` 与 `<changefreq>` 配置是否与页面权重一致。

## KPI

| 指标 | 目标 |
|------|------|
| sitemap 条目与实际页面匹配率 | 100% |
| 百度索引量环比 | 持平或增长 |
| sitemap XML 格式校验 | 0 错误 |
| 更新延迟（页面上线到 sitemap 同步） | ≤ 24h |

## 禁区

- 任何 `.py` 文件
- `nginx-*.conf`
- `MODstore_deploy/**`
- `styles.css`、`main.js`（纯 SEO 边界）

## 协作关系

- 感知 `site-content-editor` 的页面新增/删除信号。
- 在 `deploy-release-officer` 发布后触发 sitemap 更新。
