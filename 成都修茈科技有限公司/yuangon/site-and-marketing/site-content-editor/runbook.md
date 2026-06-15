# Runbook — 静态站内容编辑员

| 字段 | 值 |
|------|----|
| 员工 ID | `site-content-editor` |
| 负责区域 | site-and-marketing |
| 最后更新 | 2026-05-08 |
| 应急联系 | admin |

---

## 日常巡检

```bash
# 检查关键营销页是否可访问（替换为实际域名）
curl -o /dev/null -s -w "%{http_code}" https://xiu-ci.com/
curl -o /dev/null -s -w "%{http_code}" https://xiu-ci.com/about.html
curl -o /dev/null -s -w "%{http_code}" https://xiu-ci.com/news.html

# 校验 news 源数据 JSON 格式（canonical）
python -c "import json; json.load(open('marketing-site/data/news.json', encoding='utf-8')); print('OK')"
# 根目录 news.json 由构建脚本从 marketing-site/data 同步；仍可用以下命令做二次确认
python -c "import json; json.load(open('news.json', encoding='utf-8')); print('OK')"
python -c "import json; json.load(open('activities.json', encoding='utf-8')); print('OK')"
```

**预期输出**：每行 HTTP 200；JSON 校验输出 OK。

---

## 异常处置

### 异常 1：页面返回 404

**症状**：`curl` 返回 404。  
**排查**：确认文件名拼写、Nginx `try_files` 规则（联系 `nginx-config-engineer`）。  
**修复**：恢复文件或修正文件名；通知 `nginx-config-engineer`。

### 异常 2：JSON 格式错误

**症状**：`json.load` 抛出异常。  
**排查**：`python -m json.tool marketing-site/data/news.json`（或与根 `news.json` 对比是否未跑构建）。  
**修复**：修正 JSON 语法后在 `marketing-site/` 执行 `npm run build`，并提交同步后的根 `news.html`、`news.json`。

### 异常 3：图片路径 404

**症状**：页面图片显示 broken。  
**排查**：检查 `assets/` 目录下文件是否存在，核对 HTML `src` 属性。  
**修复**：补传图片或修正路径。

---

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |

---

## 应急升级路径

1. 静态 Skill 失败 → 动态阶段 → 超预算 → 通知 admin。
2. 页面大范围不可达 → 通知 `nginx-config-engineer` + `deploy-release-officer`。
