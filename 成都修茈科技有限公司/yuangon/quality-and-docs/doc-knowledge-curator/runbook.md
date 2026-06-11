# Runbook — 文档知识管理员

| 字段 | 值 |
|------|----|
| 员工 ID | `doc-knowledge-curator` |
| 最后更新 | 2026-05-08 |
| 应急联系 | admin |

## FHD 公开文档站（MkDocs）

`FHD/mkdocs.yml` 构建产物由 CI `CI - Docs Site` 校验；修改 `FHD/docs/` 中已纳入 `nav` 的页面后，在 FHD 根目录本地验证：

```bash
cd FHD && pip install -r requirements-docs.txt && mkdocs build
```

本员工维护 Markdown 源文件，不执行生产部署（部署见 FHD `docs-live-deploy.yml`）。

## 日常巡检

推荐一键执行（覆盖：每个 `yuangon/**/employee.yaml` 同目录需有 `README.md`、`ESkill.md` 关键章节、可选 Markdown lint）：

```bash
bash scripts/doc_health_check.sh
```

可选：若已安装 [markdownlint-cli](https://github.com/DavidAnson/markdownlint-cli) 并需全量 Markdown 检查：

```bash
DOC_HEALTH_MARKDOWNLINT=1 bash scripts/doc_health_check.sh
```

手工分步（与脚本等价，便于排障）：

```bash
# 检查所有员工 README 存在
find yuangon -name README.md | sort

# Markdown lint（如安装了 markdownlint-cli）
markdownlint "**/*.md" --ignore node_modules

# 检查 ESkill.md 关键章节
python -c "
content = open('ESkill.md').read()
for section in ['四阶段生命周期', '运行架构', '双层进化架构']:
    assert section in content, f'Missing: {section}'
print('ESkill.md OK')
"
```

CI：`.github/workflows/ci-doc-health.yml` 在 PR / `main` 推送时运行上述脚本（不含 `markdownlint`，避免额外 Node 依赖）。

## 日健康报告归档（`log-monitor-incident`）

当收到 `employee.task.done:log-monitor-incident` 或接入其产出的 Markdown 报告时：

1. **提取元数据**：解析 `report_md` 中首个 ` ```json modstore-report-meta` fenced 块，读取 `report_id`、`generated_at`、`data_sources_hash`、`error_code_map_version`、`summary_counts`。
2. **去重**：若以 `report_id` 或 `(generated_at, data_sources_hash)` 为键的存档已存在，跳过写入或追加「重复」标注。
3. **存档路径建议**：`docs/archive/daily-health/YYYY/MM/<report_id>.md`（或团队约定目录）；旁路可选保存同款 JSON meta 便于 SQL/BI。
4. **索引**：在知识库索引中登记 `employee_id`、`schema` 版本、P0/P1 计数，便于长期趋势与回归比对。
5. **契约联动**：`error_code_map_version` 变更时，交叉检查 `MODstore_deploy/docs/runbooks/incident-response.md` 是否需补充新 `code` 说明。

## 异常处置

### 异常 1：员工 README 与 employee.yaml 不一致

**排查**：对比 `employee.yaml` 中的 `scope_globs` 与 `README.md` 负责文件表。  
**修复**：更新 README（以 yaml 为准）。

### 异常 2：ESkill.md 与实现不同步

**排查**：对比 `ESkill.md` 的架构描述与 `employee_ai_scaffold.py` 实际实现。  
**修复**：更新 ESkill.md 并在文档尾部追加变更记录。

### 异常 3：文档生成员工（.xcemp）执行失败

**排查**：确认 `py-doc-generator.xcemp` / `project-doc-generator.xcemp` 在工作台可正常运行。  
**处置**：通知 `employee-pack-curator` 检查包状态。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
