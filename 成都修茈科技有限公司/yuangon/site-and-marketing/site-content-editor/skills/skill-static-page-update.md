# ESkill：静态页面内容更新（skill-static-page-update）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-static-page-update` |
| 所属员工 | `site-content-editor` |
| 业务域 | xiu-ci.com 营销静态页内容维护 |
| 版本 | 1.1.0 |
| 父版本 | — |

---

## 1. 静态阶段

**触发条件**：收到明确的内容更新指令（指定文件、指定位置、指定内容）。

**执行逻辑**：
```
识别更新类型
→ 若为新闻列表：改动 marketing-site/data/news.json → npm run build（在 marketing-site）
→ 若为其它页：改动根目录 HTML（仅 `<main>`/正文；切勿手写页眉导航）或通过构建模板
→ HTML 自检（htmlhint / 结构校验）→ 核对图片路径
→ 输出变更摘要
```

**输出 schema**：
```json
{
  "status": "ok | error",
  "changed_files": ["index.html"],
  "diff_summary": "...",
  "w3c_errors": 0,
  "broken_image_paths": []
}
```

**工具**：文件读写、`marketing-site/npm run build`、`python -m http.server`（本地预览）

**禁区提醒**：根的 `*.html` 中 **`<header>`、移动菜单** 均由 `marketing-site` 模板生成；手改会被下次构建覆盖。应改 `marketing-site/templates/partials/header.njk`（需沟通 `deploy-release-officer`/CI）。
---

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | 文件解析失败（编码错误、HTML 结构损坏） |
| 结果不达标 | `w3c_errors > 0` 或 `broken_image_paths` 非空 |
| 场景特殊 | 需要新增从未出现过的 HTML 结构段 |

---

## 3. 动态自适应阶段

**预算**：3000 tokens，4 步。  
**允许改动**：`scope_globs` 内的 HTML/CSS/JSON，禁止触碰 `forbidden_globs`。  
**LLM 任务**：生成修复 W3C 错误的 HTML diff 或补全缺失图片路径的替代方案。

---

## 4. 固化

**验收标准**：
- [x] `w3c_errors == 0`
- [x] `broken_image_paths == []`
- [x] 页面在本地 HTTP server 下正常渲染

**固化后**：将成功的补丁合并为新的标准替换流程，递增版本号。
