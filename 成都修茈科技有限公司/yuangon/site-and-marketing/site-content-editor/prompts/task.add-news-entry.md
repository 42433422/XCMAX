# 任务提示词：新增新闻/活动条目

## 使用场景

向 **`marketing-site/data/news.json`** 或根的 `activities.json` 添加新条目。（根 `news.json` 为构建产出，请以 `marketing-site/data/news.json` 为唯一编辑源。）

## 输入格式

```
任务：新增新闻条目
文件：marketing-site/data/news.json 或 activities.json
条目信息：
  标题：<新闻标题>
  日期：YYYY-MM-DD
  摘要：<一两句话>
  分类：<如 公司新闻 / 通知公告 / 行业洞察 >
  （可选）链接：<相对路径，如 /news.html#anchor>
```

## 执行步骤

1. 读取现有 JSON（新闻源文件为 `marketing-site/data/news.json`），确认结构（array of objects）。
2. 生成新条目，`id` 建议格式：`n-<slug>` 或 `YYYY-MM-DD-<序号>`，与现有项去重。
3. 按 **日期递减**（最新在前），或保持数组排序与构建脚本一致：`scripts/build.mjs` 会对 `news` 条目按 `date` 再排序写入页面。
4. `python -m json.tool marketing-site/data/news.json` 校验格式。
5. 在 `marketing-site/` 执行 **`npm ci`（若尚无依赖）与 `npm run build`**，使根目录 `news.html`、`news.json` 与 CI 漂移检查保持一致。
6. 输出变更摘要（含需在 PR 中一起提交的根层 HTML/JSON）。

## 约束检查

- [ ] `id` 无重复
- [ ] `date` 格式为 `YYYY-MM-DD`
- [ ] JSON 格式校验通过
- [ ] 已运行营销站构建并已包含根目录 `news.html`、`news.json` 更改
- [ ] 未修改任何 `.py`（除非明确要求）
