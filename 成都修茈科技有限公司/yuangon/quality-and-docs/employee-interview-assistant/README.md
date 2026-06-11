# employee-interview-assistant（员工信息访谈员）

编制岗位：**协助其他员工岗位补全说明字段**（yuangon `employee.yaml`、runbook、技能清单、依赖与风险），并通过问诊式对话收敛缺口。

## 打包进 MODstore catalog 时（manifest.json）

为启用「每日岗位方案」**定制调研方向**，请在 `employee_config_v2.metadata` 中带上其一：

```json
{
  "employee_config_v2": {
    "metadata": {
      "daily_brief_seed": "AI 员工岗位：结构化访谈、元数据与 runbook 补全、跨岗位依赖梳理；MODstore 编制与 yuangon 员工包规范；行业公开的最佳实践：知识库与提示工程"
    }
  }
}
```

同等字段名也可使用 `daily_brief_research_focus`。若未写，服务器仍可用环境变量 `MODSTORE_DAILY_BRIEF_SEEDS_JSON` 按 `pkg_id` 覆盖（见 `MODstore_deploy/.env.example`）。

## 与 `resolve_daily_brief_research_brief` 的对应关系

1. `MODSTORE_DAILY_BRIEF_SEEDS_JSON` 中 `employee-interview-assistant` 键（最高优先级）
2. 上架包 manifest 中上述 metadata 字段
3. 代码内默认回退句式（ display_name + pkg_id + 运维关键词）

## 岗位 README 中「运行依赖」填写示例

在 `yuangon/<分区>/<员工-id>/README.md` 建议单独一小节（或与「协作关系」合并），便于策展与质检交叉核对；声明对外部 API、知识库或其它 AI 岗位的依赖，不包含密钥明文。

**YAML 侧（`employee.yaml`）**：与编制矩阵一致的岗位 ID 列表。

```yaml
depends_on:
  - doc-knowledge-curator
  - modstore-backend-api
```

**README 侧（人类可读 + 运维视角）**：说明依赖的性质与失效时的行为。

```markdown
## 运行依赖

| 依赖类型 | 说明 | 失效时行为 |
|----------|------|------------|
| 岗位包 | `modstore-backend-api`：调用市场目录与工单 HTTP API | 降级为只读本地缓存目录；写操作标注待同步 |
| 知识库 | 平台向量索引 `kb_ops_incidents`（只读检索） | 输出中注明「未检索」并建议人工补链接 |
| 外部 API | 第三方天气 HTTP（可选，`WEATHER_API_BASE`） | 跳过该字段，报告其余部分 |
```

上架 MODstore 时，可在 `employee_config_v2.metadata` 中同步机器可读摘要（与 `employee-pack-curator` README 中的扩展示例一致），便于流水线与质检脚本解析。

## 文档联动

- **`doc-knowledge-curator`**：各岗位 README 中「访谈与补全目的」等公共说明由其维护排版与矩阵一致性；本岗位产出草案后可交由其落地。
- **`employee-pack-curator`**：包元数据扩展示例（含能力与依赖字段）见该员工 README「包元数据扩展示例」章节。
