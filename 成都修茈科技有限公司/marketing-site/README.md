# 营销静态站构建（xiu-ci.com 官网片段）

产出仍落在**仓库根目录**（`/news.html`、`/news.json` 及已纳入构建的若干 `*.html`），与腾讯云 Pages「整包上传站点根路径」的习惯一致。

## 源文件

| 路径 | 用途 |
|------|------|
| `data/news.json` | 新闻资讯唯一数据源 |
| `templates/partials/header.njk` | 桌面/移动导航骨架 |
| `templates/news-page.njk` | 新闻页正文 |
| `templates/shell.njk` | 常规页：`head` + `header.njk` + 原文 main/footer |
| `scripts/build.mjs` | 拼装并写回仓库根 |

## 流程

```bash
cd marketing-site
npm ci
npm run build
```

- 请勿在仓库根目录**手改导航/页眉**：构建会用 `partials/header.njk` 覆盖。
- `news.json` 根路径文件由构建从 `data/news.json` 复制，请以 `marketing-site/data/news.json` 为准编辑。
