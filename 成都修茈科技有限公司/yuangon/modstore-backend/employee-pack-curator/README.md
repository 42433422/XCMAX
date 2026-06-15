# 员工包策展员（employee-pack-curator）

## 一句话职责

管理 MODstore 员工包的完整生命周期：从 AI scaffold 生成、ESkill 注册、executor 执行，到 `.xcemp` 导入导出与 ESkill 演化固化；同时全权负责员工包相关文档的准确性与代码-文档同步；是平台员工能力的生产与演化中心。

## 负责文件

| 文件 | 说明 |
|------|------|
| `employee_ai_scaffold.py` | AI 员工脚手架生成 |
| `employee_ai_pipeline.py` | 生成流水线 |
| `employee_bench.py` | 员工测试台 |
| `employee_executor.py` | 执行引擎 |
| `employee_skill_register.py` | Skill 注册表 |
| `employee_pack_export.py` | .xcemp 导出 |
| `employee_pack_blueprints_template.py` | 蓝图模板 |
| `services/employee.py` | 员工服务层 |
| `integrations/vibe_eskill_adapter.py` | vibe-coding 桥接 |
| `market_files/*.xcemp` | 上架的员工包 |
| `docs/fhd-employee-composition.md` | 员工组成说明（A/B/C 三种形态） |
| `docs/modstore/员工制作增强设计方案.md` | 员工制作增强设计方案 |
| `MODstore_deploy/docs/employee_publish_wizard.md` | 员工发布向导 |
| `docs/adr/0003-artifacts-bundles-employee-packs.md` | 员工包架构决策记录 |

## 典型任务

1. 从 `yuangon/` 员工定义导出新员工为 `.xcemp` 并入库。
2. ESkill 动态阶段成功后执行固化（递增版本、写注册表）。
3. 修复员工 executor 执行异常。
4. 更新 `vibe_eskill_adapter.py` 以支持新的 vibe-coding 接口。
5. 审计 Skill 注册表中的孤儿 Skill（无员工引用）。
6. 验证导出的 `.xcemp` 双身份（本地独立 CLI）功能是否正常。
7. 代码变更后检查并同步员工包相关文档（`fhd-employee-composition.md`、`员工制作增强设计方案.md` 等）。
8. 新增员工形态或打包流程变更时，更新 `docs/adr/0003-artifacts-bundles-employee-packs.md` 架构决策记录。

## .xcemp 双身份说明

从 2026-05 起，所有通过 `employee_pack_export._build_employee_pack_zip_with_source`
导出的 `.xcemp` 文件同时具备**平台员工包**与 **Python zipapp CLI** 双重身份：

```bash
# 上架平台（不变）
上传至 Catalog → MODstore 装载 manifest.json + backend/

# 本地独立测试（新增）
python <pack_id>.xcemp info                      # 打印摘要
python <pack_id>.xcemp validate                  # 零依赖结构校验
python <pack_id>.xcemp run                       # no-llm 机械检查
python <pack_id>.xcemp run --input task.json     # 传入具体任务
python <pack_id>.xcemp run --llm                 # 需 OPENAI_API_KEY 或 DEEPSEEK_API_KEY
```

**零侵入**：`standalone/` 目录与顶层 `__main__.py` 对平台运行时完全透明；
老 `.xcemp` 导入平台不受影响。

制作流水线在「包体与 Python 校验」之后追加了 **独立可执行自检**（`standalone_smoke`）
步骤，自动验证导出的 `.xcemp` 可作为 zipapp 运行，失败时降级为 warning 不阻断发布。

## KPI

| 指标 | 目标 |
|------|------|
| .xcemp 导出成功率 | ≥ 99% |
| ESkill 固化周期 | ≤ 24h（动态成功后）|
| 注册表一致性检查通过率 | 100% |
| 文档-代码一致性率 | ≥ 95% |
| 文档同步延迟 | ≤ 24h（代码变更后）|

## 禁区

- `payment_*.py`
- `MODstore_deploy/market/src/**`
- `_local_secrets/**`

## 协作关系

- 与 `mods-and-eskill-curator` 协同管理 `mods/` 和 `eskill-prototype/`。
- 依赖 `vibe-coding-maintainer` 提供 vibe-coding 接口稳定性。
- 与 `doc-knowledge-curator` 协作：员工包专属文档由本员工全权负责，通用文档由 `doc-knowledge-curator` 维护。
- 与 `employee-interview-assistant` 协作：访谈技能中的「能力说明」结构化维度与下方 `metadata` 扩展示例对齐，便于各 `.xcemp` / yuangon 包统一采纳。

## 包元数据扩展示例（与访谈员联动）

上架 `manifest.json` 中可在 `employee_config_v2.metadata` 增加人类与机器均可读的摘要字段（键名约定为项目内协作用，未写入 OpenAPI 亦可作为文档契约）。**示例**：

```json
{
  "employee_config_v2": {
    "metadata": {
      "daily_brief_seed": "数字员工：数据处理 / 流程自动化 / 决策逻辑 / 协作边界；工具链：编排、RAG、可选外部 API",
      "capability_summary": {
        "data_processing": "输入工单 JSON；只读检索向量库切片；输出固定模板 Markdown",
        "workflow_automation": "编排触发 → 校验 → 检索 → 单轮 LLM → 校验 → 日志",
        "decision_logic": "须附引用；不确定显式声明；高风险操作建议拒答与 escalate",
        "collaboration_boundary": "depends_on doc-knowledge-curator；禁写 _local_secrets"
      },
      "runtime_dependencies": {
        "employee_packages": ["doc-knowledge-curator", "modstore-backend-api"],
        "external_apis": ["可选：WEATHER_API_BASE 天气查询"],
        "knowledge_bases": ["kb_ops_incidents 只读"],
        "toolchains_note": "可与 LangChain/RAGFlow 等栈类比声明编排与检索方式（仅说明，不绑定实现）"
      }
    }
  }
}
```

新打包包体可在 README 或 `tasks/` 说明中引用同一 JSON 片段，保持 yuangon 源仓库与 catalog 元数据一致。
